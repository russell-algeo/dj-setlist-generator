"""Track recognition using Shazam with checkpoint support."""

import asyncio
from pathlib import Path
from shazamio import Shazam
from dataclasses import dataclass, asdict
from typing import Optional
import json
from config import Config

@dataclass
class Recognition:
    """Recognition result from Shazam."""
    timestamp: float
    track_title: Optional[str]
    artist: Optional[str]
    shazam_confidence: Optional[float]
    shazam_track_id: Optional[str]
    raw_data: Optional[dict]
    recognized: bool
    segment_index: int

class TrackRecognizer:
    """Recognize tracks using Shazam with checkpoint support."""
    
    def __init__(self, checkpoint_manager=None):
        self.shazam = Shazam()
        self.checkpoint_manager = checkpoint_manager
        self.checkpoint_interval = Config.CHECKPOINT_INTERVAL
        
        # Rate limiting and retry settings
        self.recognition_timeout = Config.RECOGNITION_TIMEOUT
        self.max_retries = Config.MAX_RETRIES
        self.base_delay = Config.BASE_DELAY
        self.backoff_delay = Config.BACKOFF_DELAY
    
    async def recognize_segment_with_timeout(self, segment: dict, attempt: int = 1, force_fresh_instance: bool = False) -> Recognition:
        """
        Recognize a segment with timeout and retry logic.
        
        Args:
            segment: Segment info dict
            attempt: Current attempt number
            force_fresh_instance: If True, create a fresh Shazam instance
        
        Returns:
            Recognition object
        """
        try:
            # Create fresh Shazam instance only if forced (after timeout)
            if force_fresh_instance:
                print(f"  🔄 Creating fresh Shazam instance after timeout")
                shazam = Shazam()
            else:
                shazam = self.shazam
            
            # Use asyncio.wait_for to add timeout
            result = await asyncio.wait_for(
                shazam.recognize(str(segment['file'])),
                timeout=self.recognition_timeout
            )
            
            # Check if recognition was successful
            if 'track' in result:
                track = result['track']
                return Recognition(
                    timestamp=segment['timestamp'],
                    track_title=track.get('title'),
                    artist=track.get('subtitle'),
                    shazam_confidence=None,
                    shazam_track_id=track.get('key'),
                    raw_data=result,
                    recognized=True,
                    segment_index=segment['index']
                )
            else:
                # No match found (but API worked)
                return Recognition(
                    timestamp=segment['timestamp'],
                    track_title=None,
                    artist=None,
                    shazam_confidence=None,
                    shazam_track_id=None,
                    raw_data=result,
                    recognized=False,
                    segment_index=segment['index']
                )
        
        except asyncio.TimeoutError:
            print(f"  ⏱️  Timeout on attempt {attempt}/{self.max_retries}")
            
            if attempt < self.max_retries:
                # Exponential backoff
                wait_time = self.backoff_delay * (2 ** (attempt - 1))
                print(f"  ⏳ Waiting {wait_time:.0f}s before retry...")
                await asyncio.sleep(wait_time)
                # Force fresh instance on retry after timeout
                return await self.recognize_segment_with_timeout(segment, attempt + 1, force_fresh_instance=True)
            else:
                print(f"  ❌ Max retries reached, marking as unrecognized")
                return Recognition(
                    timestamp=segment['timestamp'],
                    track_title=None,
                    artist=None,
                    shazam_confidence=None,
                    shazam_track_id=None,
                    raw_data=None,
                    recognized=False,
                    segment_index=segment['index']
                )
        
        except Exception as e:
            print(f"  ⚠️  Error on attempt {attempt}/{self.max_retries}: {type(e).__name__}: {e}")
            
            if attempt < self.max_retries:
                wait_time = self.backoff_delay
                print(f"  ⏳ Waiting {wait_time:.0f}s before retry...")
                await asyncio.sleep(wait_time)
                # Don't force fresh instance for general errors, only timeouts
                return await self.recognize_segment_with_timeout(segment, attempt + 1, force_fresh_instance=False)
            else:
                print(f"  ❌ Max retries reached, marking as unrecognized")
                return Recognition(
                    timestamp=segment['timestamp'],
                    track_title=None,
                    artist=None,
                    shazam_confidence=None,
                    shazam_track_id=None,
                    raw_data=None,
                    recognized=False,
                    segment_index=segment['index']
                )
    
    async def recognize_segment(self, segment: dict) -> Recognition:
        """
        Recognize a single audio segment with retry logic.
        
        Args:
            segment: Segment info dict with file path and timestamp
        
        Returns:
            Recognition object
        """
        return await self.recognize_segment_with_timeout(segment, attempt=1, force_fresh_instance=False)
    
    async def recognize_all_segments(self, segments: list[dict], resume_from_checkpoint: bool = False) -> list[Recognition]:
        """
        Recognize all segments with progress reporting and checkpoint saving.
        
        Args:
            segments: List of segment info dicts
            resume_from_checkpoint: If True, try to load previous recognitions
        
        Returns:
            List of Recognition objects
        """
        recognitions = []
        start_index = 0
        
        # Try to load checkpoint
        if resume_from_checkpoint and self.checkpoint_manager:
            checkpoint = self.checkpoint_manager.load_checkpoint()
            if checkpoint and checkpoint.get('stage') == 'recognizing':
                saved_recognitions = checkpoint['data'].get('recognitions', [])
                if saved_recognitions:
                    # Reconstruct Recognition objects
                    recognitions = [
                        Recognition(**rec) for rec in saved_recognitions
                    ]
                    start_index = len(recognitions)
                    print(f"📂 Resuming from segment {start_index}/{len(segments)}")
        
        total = len(segments)
        
        if start_index == 0:
            print(f"\nRecognizing tracks from {total} segments...")
        else:
            print(f"\nContinuing recognition from segment {start_index}...")
        
        for i in range(start_index, total):
            segment = segments[i]
            
            # print(f"  [{i+1}/{total}] Processing segment at {segment['timestamp']/60:.1f}min...")
            
            recognition = await self.recognize_segment(segment)
            recognitions.append(recognition)
            
            status = "✓" if recognition.recognized else "✗"
            track_info = f"{recognition.artist} - {recognition.track_title}" if recognition.recognized else "Not recognized"
            
            print(f"  [{i+1}/{total}] {segment['timestamp']/60:.1f}min {status} {track_info}")
            
            # Save checkpoint periodically
            if self.checkpoint_manager and (i + 1) % self.checkpoint_interval == 0:
                self._save_recognition_checkpoint(recognitions)
            
            # Adaptive delay between requests
            # Longer delay after errors/timeouts, shorter after success
            if recognition.recognized:
                await asyncio.sleep(self.base_delay)
            else:
                # If not recognized, it might have been a timeout/error
                # Use longer delay to avoid rate limiting
                await asyncio.sleep(self.base_delay * 2)
        
        # Save final checkpoint
        if self.checkpoint_manager:
            self._save_recognition_checkpoint(recognitions)
        
        print(f"\nRecognition complete: {sum(1 for r in recognitions if r.recognized)}/{total} segments recognized")
        return recognitions
    
    def _save_recognition_checkpoint(self, recognitions: list[Recognition]):
        """Save recognitions to checkpoint."""
        if not self.checkpoint_manager:
            return
        
        # Convert Recognition objects to dicts for JSON serialization
        serializable_recognitions = []
        for rec in recognitions:
            rec_dict = asdict(rec)
            # Remove raw_data to keep checkpoint file size manageable
            rec_dict['raw_data'] = None
            serializable_recognitions.append(rec_dict)
        
        self.checkpoint_manager.save_checkpoint('recognizing', {
            'recognitions': serializable_recognitions,
            'count': len(recognitions)
        })