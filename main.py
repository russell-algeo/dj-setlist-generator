"""Main entry point for setlist generator."""

import asyncio
import sys
from pathlib import Path
from config import Config
from audio_downloader import AudioDownloader
from audio_segmenter import AudioSegmenter
from track_recognizer import TrackRecognizer
from setlist_builder import SetlistBuilder
from metadata_enricher import MetadataEnricher
from output_formatter import OutputFormatter
from checkpoint_manager import CheckpointManager

class SetlistGenerator:
    """Main orchestrator for setlist generation."""

    def __init__(self):
        self.builder = SetlistBuilder()
        self.enricher = MetadataEnricher()

    def _create_spotify_playlist(self, enriched_tracks: list, mix_info: dict, playlist_name: str):
        """Handle Spotify playlist creation with user confirmation."""
        from spotify_playlist_creator import SpotifyPlaylistCreator

        print("\n" + "=" * 70)
        print("SPOTIFY PLAYLIST")
        print("=" * 70)

        # Check if auto-create is enabled or prompt user
        if Config.AUTO_CREATE_SPOTIFY_PLAYLIST:
            print("Auto-creating Spotify playlist...")
            create_playlist = True
        else:
            print("Review the setlist above before creating a Spotify playlist.")
            user_input = input("\nCreate Spotify playlist from this setlist? (y/n): ").lower()
            create_playlist = user_input == 'y'

        if not create_playlist:
            print("Skipped playlist creation")
            return

        creator = SpotifyPlaylistCreator()
        result = creator.create_playlist_from_setlist(
            enriched_tracks=enriched_tracks,
            mix_info=mix_info,
            playlist_name=playlist_name
        )

        if result:
            print("\n" + "=" * 70)
            print("PLAYLIST CREATED SUCCESSFULLY!")
            print("=" * 70)
            print(f"Playlist URL: {result['playlist_url']}")
            print(f"Tracks added: {result['tracks_added']}/{result['tracks_with_spotify_urls']}")

            if result['tracks_failed'] > 0:
                print(f"Warning: {result['tracks_failed']} tracks failed to add")

            unknown_count = result['total_tracks_in_setlist'] - result['tracks_with_spotify_urls']
            if unknown_count > 0:
                print(f"Note: {unknown_count} tracks skipped (unknown or no Spotify URL)")
        else:
            print("\nPlaylist creation failed or was cancelled")

    async def generate(self, url: str, output_name: str = None, resume: bool = True):
        """
        Generate setlist from URL.
        
        Args:
            url: YouTube or SoundCloud URL
            output_name: Optional custom name for output files
            resume: If True, resume from checkpoint if available
        """
        print("=" * 70)
        print("DJ SET SETLIST GENERATOR")
        print("=" * 70)
        
        # Step 1: Get video info first to get mix name
        print("\n[1/6] Fetching video information...")
        temp_downloader = AudioDownloader()
        mix_info = temp_downloader.get_video_info(url)
        mix_info['url'] = url  # Store original URL for playlist description
        mix_name = mix_info['title']
        
        print(f"  Title: {mix_name}")
        print(f"  Duration: {mix_info['duration']/60:.1f} minutes")
        print(f"  Uploader: {mix_info['uploader']}")
        
        # Initialize checkpoint manager with mix name (single source of truth for paths)
        checkpoint_manager = CheckpointManager(url, mix_name)
        mix_id = checkpoint_manager.mix_id

        print(f"\n📁 Directory structure:")
        print(f"  Assets: {checkpoint_manager.assets_dir}")
        print(f"  Checkpoints: {checkpoint_manager.checkpoint_dir}")
        print(f"  Output: {checkpoint_manager.output_dir}")

        # Initialize components with mix-specific directories
        downloader = AudioDownloader(assets_dir=checkpoint_manager.assets_dir)
        segmenter = AudioSegmenter(mix_id=mix_id, assets_dir=checkpoint_manager.assets_dir)
        recognizer = TrackRecognizer(checkpoint_manager=checkpoint_manager)
        formatter = OutputFormatter(output_dir=checkpoint_manager.output_dir)
        
        # Check for existing checkpoint
        checkpoint = None
        if resume and Config.ENABLE_CHECKPOINTS:
            checkpoint = checkpoint_manager.load_checkpoint()
            if checkpoint:
                print(f"📂 Resuming from checkpoint (stage: {checkpoint['stage']})")
        
        # Validate configuration
        issues = Config.validate()
        if issues:
            print("\n⚠ Configuration warnings:")
            for issue in issues:
                print(f"  - {issue}")
            print()
        
        try:
            # Step 2: Download audio (or skip if exists)
            print("\n[2/6] Downloading audio...")
            audio_path = checkpoint_manager.get_audio_path()
            audio_file = downloader.download(url, output_path=audio_path)
            
            if not checkpoint or checkpoint['stage'] in ['downloaded', 'audio_only']:
                checkpoint_manager.save_checkpoint('downloaded', {
                    'audio_file': str(audio_file),
                    'mix_info': mix_info
                })
            
            # Step 3: Segment audio (or load existing)
            print("\n[3/6] Segmenting audio...")
            segments = segmenter.create_segments(audio_file, force_recreate=False)
            
            if not checkpoint or checkpoint['stage'] in ['downloaded', 'segmented']:
                checkpoint_manager.save_checkpoint('segmented', {
                    'audio_file': str(audio_file),
                    'segment_count': len(segments),
                    'mix_info': mix_info
                })
            
            # Step 4: Recognize tracks (with resume support)
            print("\n[4/6] Recognizing tracks...")
            should_resume = checkpoint and checkpoint['stage'] == 'recognizing'
            recognitions = await recognizer.recognize_all_segments(
                segments, 
                resume_from_checkpoint=should_resume
            )
            
            # Step 5: Build setlist
            print("\n[5/6] Building setlist...")
            tracks = self.builder.build_setlist(recognitions)
            tracks = self.builder.add_unknown_tracks(tracks, recognitions)
            
            # Print summary
            print("\n" + "=" * 70)
            print("SETLIST SUMMARY")
            print("=" * 70)
            for i, track in enumerate(tracks, 1):
                confidence_icon = {
                    'HIGH': '🟢',
                    'MEDIUM': '🟡',
                    'LOW': '🟠',
                    'UNCERTAIN': '⚪'
                }.get(track.confidence, '⚪')
                
                time_str = f"{int(track.start_time//60)}:{int(track.start_time%60):02d}"
                print(f"{i:2d}. [{time_str}] {confidence_icon} {track.artist} - {track.title}")
            
            # Step 6: Enrich and save
            print("\n[6/6] Enriching metadata and saving...")
            enriched_tracks = self.enricher.enrich_all_tracks(tracks)
            
            # Save outputs (use custom name or mix name)
            final_output_name = output_name or Config._sanitize_filename(mix_name)
            json_file = formatter.save_json(enriched_tracks, mix_info, final_output_name)
            md_file = formatter.save_markdown(enriched_tracks, mix_info, final_output_name)
            
            # Cleanup
            print("\nCleaning up...")
            segmenter.cleanup_segments(segments)

            if Config.CLEANUP_TEMP_FILES:
                audio_file.unlink()
                print("🗑️  Deleted audio file")
            else:
                print(f"💾 Kept audio file: {audio_file}")

            checkpoint_manager.clear_checkpoint()

            print("\n" + "=" * 70)
            print("COMPLETE!")
            print("=" * 70)
            print(f"JSON output: {json_file}")
            print(f"Markdown output: {md_file}")

            # Spotify Playlist Creation
            if Config.ENABLE_SPOTIFY_PLAYLISTS:
                self._create_spotify_playlist(enriched_tracks, mix_info, final_output_name)

            if not Config.CLEANUP_TEMP_FILES:
                print(f"\nAssets preserved in: {checkpoint_manager.assets_dir}")
            if not Config.CLEANUP_CHECKPOINTS:
                print(f"Checkpoint preserved: {checkpoint_manager.checkpoint_file}")

            return mix_name

        except KeyboardInterrupt:
            print("\n\n⚠️  Process interrupted!")
            print("Progress has been saved. Run again with the same URL to resume.")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            print("\n💾 Progress has been saved. Run again with the same URL to resume.")
            sys.exit(1)

async def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python main.py <url1> [url2] [url3] ... [--no-resume]")
        print("\nExample:")
        print("  python main.py https://www.youtube.com/watch?v=xxxxx")
        print("  python main.py url1 url2 url3  # Process multiple URLs sequentially")
        print("  python main.py url1 url2 --no-resume")
        sys.exit(1)

    urls = []
    resume = True

    # Parse arguments - collect URLs and flags
    for arg in sys.argv[1:]:
        if arg == '--no-resume':
            resume = False
        elif arg.startswith('http://') or arg.startswith('https://'):
            urls.append(arg)
        else:
            print(f"Warning: Ignoring unrecognized argument: {arg}")

    if not urls:
        print("Error: No valid URLs provided")
        sys.exit(1)

    # Ensure base directories exist
    Config.ensure_directories()

    generator = SetlistGenerator()

    # Process each URL sequentially
    results = []
    for i, url in enumerate(urls, 1):
        print("\n" + "█" * 70)
        print(f"█ PROCESSING URL {i}/{len(urls)}")
        print("█" * 70)
        print(f"█ {url}")
        print("█" * 70 + "\n")

        try:
            mix_name = await generator.generate(url, output_name=None, resume=resume)
            results.append((url, "SUCCESS", mix_name))
        except Exception as e:
            print(f"\n❌ Failed to process: {url}")
            print(f"   Error: {e}")
            results.append((url, f"FAILED: {e}", None))

    # Print summary if multiple URLs were processed
    if len(urls) > 1:
        print("\n" + "=" * 70)
        print("BATCH PROCESSING SUMMARY")
        print("=" * 70)
        for url, status, mix_name in results:
            status_icon = "✅" if status == "SUCCESS" else "❌"
            display_name = mix_name if mix_name else url[:60]
            print(f"{status_icon} {display_name}")
            if status != "SUCCESS":
                print(f"   {status}")

        success_count = sum(1 for _, s, _ in results if s == "SUCCESS")
        print(f"\nCompleted: {success_count}/{len(urls)} successful")

if __name__ == '__main__':
    asyncio.run(main())