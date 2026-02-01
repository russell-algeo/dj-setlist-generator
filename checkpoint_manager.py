"""Checkpoint management for crash recovery."""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from config import Config
from typing import Optional

class CheckpointManager:
    """Manage checkpoints for crash recovery with organized directory structure."""
    
    def __init__(self, url: str, mix_name: str):
        """
        Initialize checkpoint manager.
        
        Args:
            url: URL of the mix
            mix_name: Name of the mix (from video title)
        """
        self.url = url
        self.mix_name = mix_name
        
        # Create unique identifier for this mix based on URL
        self.mix_id = hashlib.md5(url.encode()).hexdigest()[:12]
        
        # Get organized directory structure
        dirs = Config.get_mix_directories(mix_name)
        self.assets_dir = dirs['assets']
        self.checkpoint_dir = dirs['checkpoints']
        self.output_dir = dirs['output']
        
        # Ensure directories exist
        Config.ensure_mix_directories(mix_name)
        
        # File paths
        self.checkpoint_file = self.checkpoint_dir / f"checkpoint_{self.mix_id}.json"
        self.audio_file = self.assets_dir / f"mix_{self.mix_id}.mp3"
    
    def save_checkpoint(self, stage: str, data: dict):
        """
        Save checkpoint data.
        
        Args:
            stage: Current stage (e.g., 'downloaded', 'segmented', 'recognized')
            data: Data to save
        """
        if not Config.ENABLE_CHECKPOINTS:
            return
        
        checkpoint = {
            'mix_id': self.mix_id,
            'mix_name': self.mix_name,
            'url': self.url,
            'stage': stage,
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        
        with open(self.checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        
        print(f"💾 Checkpoint saved: {stage}")
    
    def load_checkpoint(self) -> Optional[dict]:
        """
        Load existing checkpoint if it exists.
        
        Returns:
            Checkpoint data or None
        """
        if not Config.ENABLE_CHECKPOINTS:
            return None
        
        if not self.checkpoint_file.exists():
            return None
        
        try:
            with open(self.checkpoint_file, 'r') as f:
                checkpoint = json.load(f)
            
            print(f"📂 Found checkpoint from {checkpoint['timestamp']}")
            print(f"   Mix: {checkpoint.get('mix_name', 'Unknown')}")
            print(f"   Stage: {checkpoint['stage']}")
            return checkpoint
        
        except Exception as e:
            print(f"⚠️  Could not load checkpoint: {e}")
            return None
    
    def clear_checkpoint(self):
        """Delete checkpoint file after successful completion."""
        if not Config.CLEANUP_CHECKPOINTS:
            print(f"💾 Keeping checkpoint file: {self.checkpoint_file}")
            return
        
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            print("🗑️  Checkpoint cleared")
    
    def get_audio_path(self) -> Path:
        """Get the path where audio should be saved/loaded."""
        return self.audio_file
    
    def audio_exists(self) -> bool:
        """Check if audio file already exists."""
        return self.audio_file.exists()
    
    def segments_exist(self) -> bool:
        """Check if segment files exist."""
        segment_files = list(self.assets_dir.glob(f"segment_{self.mix_id}_*.mp3"))
        return len(segment_files) > 0
    
    def list_existing_segments(self) -> list[Path]:
        """List all existing segment files for this mix."""
        return sorted(self.assets_dir.glob(f"segment_{self.mix_id}_*.mp3"))
    
    def get_output_dir(self) -> Path:
        """Get the output directory for this mix."""
        return self.output_dir