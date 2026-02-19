"""Main entry point for setlist generator."""

import asyncio
import sys
from pathlib import Path
from config import Config
from notifier import Notifier
from audio_downloader import AudioDownloader
from audio_segmenter import AudioSegmenter
from track_recognizer import TrackRecognizer, Recognition
from setlist_builder import SetlistBuilder, CONFIDENCE_ICONS
from metadata_enricher import MetadataEnricher
from output_formatter import OutputFormatter, format_time
from html_formatter import HtmlFormatter
from checkpoint_manager import ArtistManager, CheckpointManager, sanitize_filename

class SetlistGenerator:
    """Main orchestrator for setlist generation."""

    def __init__(self):
        self.builder = SetlistBuilder()
        self.enricher = MetadataEnricher()

    async def generate(self, url: str, output_name: str = None, resume: bool = True,
                       artist_name: str = None):
        """
        Generate setlist from URL.

        Args:
            url: YouTube or SoundCloud URL
            output_name: Optional custom name for output files
            resume: If True, resume from checkpoint if available
            artist_name: Optional artist name (artist discovery mode).
                         When provided, nests checkpoints under the artist directory.

        Returns:
            Tuple of (mix_name, output_dir_path, skipped) where skipped is True
            if the set was already fully processed and no work was done.
        """
        print("=" * 70)
        print("DJ SET SETLIST GENERATOR")
        print("=" * 70)

        # Step 1: Get video info first to get mix name
        print("\n[1/5] Fetching video information...")
        temp_downloader = AudioDownloader()
        mix_info = temp_downloader.get_video_info(url)
        mix_info['url'] = url  # Store original URL for playlist description
        mix_name = mix_info['title']

        print(f"  Title: {mix_name}")
        print(f"  Duration: {mix_info['duration']/60:.1f} minutes")
        print(f"  Uploader: {mix_info['uploader']}")

        # Initialize checkpoint manager with mix name (single source of truth for paths)
        checkpoint_manager = CheckpointManager(url, mix_name, artist_name=artist_name)

        print(f"\n📁 Directory structure:")
        print(f"  Assets: {checkpoint_manager.assets_dir}")
        print(f"  Checkpoints: {checkpoint_manager.checkpoint_dir}")
        print(f"  Output: {checkpoint_manager.output_dir}")

        # Initialize components — each pulls its directories from checkpoint_manager
        downloader = AudioDownloader(checkpoint_manager=checkpoint_manager)
        segmenter = AudioSegmenter(checkpoint_manager=checkpoint_manager)
        recognizer = TrackRecognizer(checkpoint_manager=checkpoint_manager)
        formatter = OutputFormatter(checkpoint_manager=checkpoint_manager)
        html_formatter = HtmlFormatter(checkpoint_manager=checkpoint_manager)

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
            # Skip if already fully processed (including playlist creation)
            if checkpoint and checkpoint['stage'] == 'completed':
                return mix_name, str(checkpoint_manager.output_dir), True

            # Check if we have complete recognition data from a previous run
            # but still need to process and create a playlist
            if checkpoint and checkpoint['stage'] == 'recognized':
                print("\n✅ Found complete recognition data from previous run!")
                print("   Skipping download, segmentation, and recognition...")

                saved_recognitions = checkpoint['data'].get('recognitions', [])
                recognitions = [Recognition.from_checkpoint(rec) for rec in saved_recognitions]
                print(f"   Loaded {len(recognitions)} recognition results")

                audio_file = None
            else:
                # Normal flow: download, then stream segment+recognize.

                # Step 2: Download audio (or skip if exists)
                print("\n[2/5] Downloading audio...")
                audio_path = checkpoint_manager.audio_file
                audio_file = downloader.download(url, output_path=audio_path)

                if not checkpoint or checkpoint['stage'] in ['downloaded', 'audio_only']:
                    checkpoint_manager.save_checkpoint('downloaded', {
                        'audio_file': str(audio_file),
                        'mix_info': mix_info
                    })

                # Step 3: Streaming recognition — segments are created on-the-fly
                # via FFmpeg (no full-file RAM load), recognized, then deleted
                # immediately after each batch.  This avoids writing all 250-400
                # segment files to disk before recognition can begin.
                #
                # Checkpoint resume logic:
                #   'recognizing' → partial results exist; skip already-done segments.
                #   'segmented'   → legacy pre-streaming checkpoint; segment files are
                #                   gone, so we treat this as a fresh recognition run.
                #   'downloaded'  → nothing done yet; start from segment 0.
                print("\n[3/5] Streaming recognition (segment + recognize on-the-fly)...")
                should_resume = bool(checkpoint and checkpoint['stage'] == 'recognizing')
                recognitions = await recognizer.recognize_segments_streaming(
                    audio_file,
                    mix_duration=mix_info['duration'],
                    segmenter=segmenter,
                    resume_from_checkpoint=should_resume,
                )

            # Step 4: Build setlist
            print("\n[4/5] Building setlist...")
            tracks = self.builder.build_setlist(recognitions)
            tracks = self.builder.add_unknown_tracks(tracks, recognitions)

            # Print summary
            print("\n" + "=" * 70)
            print("SETLIST SUMMARY")
            print("=" * 70)
            for i, track in enumerate(tracks, 1):
                icon = CONFIDENCE_ICONS.get(track.confidence, '⚪')
                print(f"{i:2d}. [{format_time(track.start_time)}] {icon} {track.artist} - {track.title}")

            # Step 5: Enrich and save
            print("\n[5/5] Enriching metadata and saving...")
            enriched_tracks = self.enricher.enrich_all_tracks(tracks)

            # Save outputs (use custom name or mix name)
            final_output_name = output_name or sanitize_filename(mix_name)
            json_file = formatter.save_setlist_json(enriched_tracks, mix_info, final_output_name)
            md_file = formatter.save_setlist_markdown(enriched_tracks, mix_info, final_output_name)
            html_file = html_formatter.save_setlist_html(enriched_tracks, mix_info, final_output_name) if Config.ENABLE_HTML_OUTPUT else None

            print("\n" + "=" * 70)
            print("COMPLETE!")
            print("=" * 70)
            print(f"JSON output:     {json_file}")
            print(f"Markdown output: {md_file}")
            if html_file:
                print(f"HTML output:     file://{html_file.resolve()}")

            # Spotify Playlist Creation
            if Config.ENABLE_SPOTIFY_PLAYLISTS:
                from spotify_playlist_creator import SpotifyPlaylistCreator
                SpotifyPlaylistCreator.create_with_confirmation(enriched_tracks, mix_info, final_output_name)

            # Mark as fully completed (including playlist creation)
            checkpoint_manager.save_recognition_checkpoint(recognitions, stage='completed')

            # Cleanup
            print("\nCleaning up...")
            checkpoint_manager.cleanup_assets()
            checkpoint_manager.cleanup_checkpoint()

            return mix_name, str(checkpoint_manager.output_dir), False

        except KeyboardInterrupt:
            print("\n\n⚠️  Process interrupted!")
            print("Progress has been saved. Run again with the same URL to resume.")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            print("\n💾 Progress has been saved. Run again with the same URL to resume.")
            raise


def _is_url(arg: str) -> bool:
    """Check if an argument looks like a URL."""
    return arg.startswith('http://') or arg.startswith('https://')


async def process_urls(urls: list[str], resume: bool, artist_name: str = None):
    """Process a list of URLs through the setlist generation pipeline.

    Args:
        urls: List of YouTube/SoundCloud URLs.
        resume: Whether to resume from checkpoints.
        artist_name: Optional artist name (artist discovery mode).

    Returns:
        List of result dicts with keys: url, status, mix_name, output_dir
    """
    generator = SetlistGenerator()
    results = []

    for i, url in enumerate(urls, 1):
        print("\n" + "█" * 70)
        print(f"█ PROCESSING URL {i}/{len(urls)}")
        print("█" * 70)
        print(f"█ {url}")
        print("█" * 70 + "\n")

        try:
            mix_name, output_dir, skipped = await generator.generate(
                url, output_name=None, resume=resume, artist_name=artist_name
            )
            results.append({"url": url, "status": "SUCCESS", "mix_name": mix_name, "output_dir": output_dir})
            if not skipped:
                Notifier.notify_url_complete(mix_name or url[:50], i, len(urls), success=True)
        except Exception as e:
            print(f"\n❌ Failed to process: {url}")
            print(f"   Error: {e}")
            results.append({"url": url, "status": f"FAILED: {e}", "mix_name": None, "output_dir": None})
            Notifier.notify_url_complete(url[:50], i, len(urls), success=False, error=str(e))

    return results


async def process_artist(artist_name: str, resume: bool):
    """Discover and process all DJ sets for an artist.

    Args:
        artist_name: Name of the DJ/artist.
        resume: Whether to resume from checkpoints.
    """
    from dj_set_discovery import DjSetDiscoverer
    from artist_summary import ArtistSummarizer

    print("█" * 70)
    print(f"█ DJ SET DISCOVERY MODE")
    print("█" * 70)
    print(f"█ Artist: {artist_name}")
    print("█" * 70 + "\n")

    artist_mgr = ArtistManager(artist_name)
    discoverer = DjSetDiscoverer(artist_manager=artist_mgr)
    summarizer = ArtistSummarizer(artist_manager=artist_mgr)

    # Step 1: Discover sets (cached in checkpoints dir, limited by Config.MAX_SETS_PER_ARTIST)
    print("[Discovery] Searching for DJ sets...\n")
    sets = discoverer.discover()

    if not sets:
        print(f"\nNo DJ sets found for '{artist_name}'.")
        print("Try using a direct URL instead:")
        print(f'  python main.py "https://www.youtube.com/watch?v=xxxxx"')
        artist_mgr.cleanup_discovery_cache()
        return

    # Step 2: Process each discovered set
    urls = [s.url for s in sets]
    results = await process_urls(urls, resume=resume, artist_name=artist_name)

    # Step 3: Generate artist summary
    print("\n" + "█" * 70)
    print(f"█ GENERATING ARTIST SUMMARY")
    print("█" * 70 + "\n")

    summarizer.generate(results)

    # Clean up discovery cache
    artist_mgr.cleanup_discovery_cache()

    # Print final batch summary
    print("\n" + "=" * 70)
    print(f"COMPLETE: {artist_name.upper()}")
    print("=" * 70)

    success_count = sum(1 for r in results if r["status"] == "SUCCESS")
    fail_count = len(results) - success_count

    for r in results:
        icon = "✅" if r["status"] == "SUCCESS" else "❌"
        name = r["mix_name"] or r["url"][:60]
        print(f"  {icon} {name}")
        if r["status"] == "SUCCESS" and r.get("output_dir"):
            html_files = list(Path(r["output_dir"]).glob("*.html"))
            if html_files:
                print(f"     file://{html_files[0].resolve()}")
        if r["status"] != "SUCCESS":
            print(f"     {r['status']}")

    print(f"\nResults: {success_count} successful, {fail_count} failed out of {len(results)} sets")
    print(f"Output directory: {artist_mgr.output_dir}")
    print(f"Artist summary: {artist_mgr.output_dir / 'artist_summary.md'}")
    artist_html = artist_mgr.output_dir / 'artist_summary.html'
    if artist_html.exists():
        print(f"Artist summary HTML: file://{artist_html.resolve()}")

    # Send artist completion notification
    Notifier.notify_artist_complete(artist_name, success_count, len(results))


async def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py \"DJ Name\" [\"DJ Name 2\"] ...  # Discover & process all sets")
        print("  python main.py \"URL\" [URL2] ...             # Process specific URLs")
        print("")
        print("Options:")
        print("  --no-resume       Ignore checkpoints, start fresh")
        print("  (Set MAX_SETS_PER_ARTIST=N in .env to limit sets per artist)")
        print("")
        print("Examples:")
        print("  python main.py \"Dyed Soundorom\"")
        print("  python main.py \"Adam Rose\" \"Spirit Catcher\"")
        print("  python main.py https://www.youtube.com/watch?v=xxxxx")
        print("  python main.py url1 url2 url3 --no-resume")
        sys.exit(1)

    # Parse arguments
    urls = []
    artists = []
    resume = True

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--no-resume':
            resume = False
        elif _is_url(arg):
            urls.append(arg)
        else:
            artists.append(arg)
        i += 1

    # Ensure base directories exist
    Config.ensure_directories()

    # Determine mode: artist discovery vs direct URL processing
    if urls and artists:
        print("Error: Cannot mix URLs and artist names. Use one or the other.")
        sys.exit(1)

    if urls:
        # URL mode: existing behavior
        results = await process_urls(urls, resume=resume)

        if len(urls) > 1:
            print("\n" + "=" * 70)
            print("BATCH PROCESSING SUMMARY")
            print("=" * 70)
            for r in results:
                icon = "✅" if r["status"] == "SUCCESS" else "❌"
                name = r["mix_name"] or r["url"][:60]
                print(f"{icon} {name}")
                if r["status"] != "SUCCESS":
                    print(f"   {r['status']}")

            success_count = sum(1 for r in results if r["status"] == "SUCCESS")
            print(f"\nCompleted: {success_count}/{len(urls)} successful")

            batch_results = [(r["url"], r["status"]) for r in results]
            Notifier.notify_batch_complete(batch_results)

    elif artists:
        # Artist mode: discover + process (sequentially for each artist)
        for artist_idx, artist_name in enumerate(artists, 1):
            if len(artists) > 1:
                print("\n" + "▓" * 70)
                print(f"▓ ARTIST {artist_idx}/{len(artists)}: {artist_name.upper()}")
                print("▓" * 70 + "\n")
            await process_artist(artist_name, resume=resume)

    else:
        print("Error: No URLs or artist name provided")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
