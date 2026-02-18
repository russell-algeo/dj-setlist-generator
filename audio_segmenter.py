"""Audio segmentation into overlapping chunks."""

from pathlib import Path
from pydub import AudioSegment
from config import Config
import math

class AudioSegmenter:
    """Create overlapping segments from audio file."""
    
    def __init__(self, checkpoint_manager=None, segment_duration: int = None, overlap: int = None):
        """
        Initialize segmenter.

        Args:
            checkpoint_manager: CheckpointManager instance. Provides mix_id and assets_dir.
                                 If None, falls back to Config defaults.
            segment_duration: Duration of each segment in seconds
            overlap: Overlap between segments in seconds
        """
        self.segment_duration = segment_duration or Config.SEGMENT_DURATION
        self.overlap = overlap or Config.SEGMENT_OVERLAP
        self.assets_dir = checkpoint_manager.assets_dir if checkpoint_manager else Config.ASSETS_DIR
        self.mix_id = checkpoint_manager.mix_id if checkpoint_manager else "default"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
    
    def create_segments(self, audio_file: Path, force_recreate: bool = False) -> list[dict]:
        """
        Create overlapping segments from audio file.

        Args:
            audio_file: Path to audio file
            force_recreate: If True, recreate even if segments exist

        Returns:
            List of segment info dicts with timestamp and file path
        """
        # Check if segments already exist
        existing_segments = self._load_existing_segments()
        if existing_segments and not force_recreate:
            print(f"✓ Found {len(existing_segments)} existing segments, skipping segmentation")
            return existing_segments
        
        print(f"Loading audio file: {audio_file}")
        audio = AudioSegment.from_mp3(str(audio_file))
        
        duration_ms = len(audio)
        duration_sec = duration_ms / 1000
        
        segment_duration_ms = self.segment_duration * 1000
        overlap_ms = self.overlap * 1000
        step_ms = segment_duration_ms - overlap_ms
        
        num_segments = math.ceil((duration_ms - segment_duration_ms) / step_ms) + 1
        
        print(f"Audio duration: {duration_sec:.1f}s")
        print(f"Creating {num_segments} segments ({self.segment_duration}s each, {self.overlap}s overlap)")
        
        segments = []
        
        for i in range(num_segments):
            start_ms = i * step_ms
            end_ms = start_ms + segment_duration_ms
            
            # Don't go beyond audio length
            if start_ms >= duration_ms:
                break
            
            end_ms = min(end_ms, duration_ms)
            
            segment_audio = audio[start_ms:end_ms]
            segment_file = self.assets_dir / f"segment_{self.mix_id}_{i:04d}.mp3"
            
            segment_audio.export(str(segment_file), format="mp3")
            
            segments.append({
                'index': i,
                'timestamp': start_ms / 1000,  # Convert to seconds
                'duration': (end_ms - start_ms) / 1000,
                'file': segment_file
            })
        
        print(f"Created {len(segments)} segments")
        return segments
    
    def _load_existing_segments(self) -> list[dict]:
        """Load information about existing segment files."""
        segment_files = sorted(self.assets_dir.glob(f"segment_{self.mix_id}_*.mp3"))
        
        if not segment_files:
            return []
        
        segments = []
        for segment_file in segment_files:
            # Extract index from filename: segment_MIXID_0001.mp3
            filename = segment_file.stem
            parts = filename.split('_')
            if len(parts) >= 3:
                try:
                    index = int(parts[-1])
                    timestamp = index * (self.segment_duration - self.overlap)
                    
                    segments.append({
                        'index': index,
                        'timestamp': timestamp,
                        'duration': self.segment_duration,
                        'file': segment_file
                    })
                except ValueError:
                    continue
        
        return sorted(segments, key=lambda x: x['index'])
    
