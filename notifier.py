"""Send notifications via ntfy.sh."""

import urllib.request
import urllib.error
from config import Config


class Notifier:
    """Send notifications via ntfy.sh."""

    @staticmethod
    def send(message: str, title: str = None, tags: str = None):
        """Send a notification if NTFY_TOPIC is configured."""
        if not Config.NTFY_TOPIC:
            return

        url = f"https://ntfy.sh/{Config.NTFY_TOPIC}"
        data = message.encode('utf-8')

        req = urllib.request.Request(url, data=data, method='POST')
        if title:
            req.add_header('Title', title)
        if tags:
            req.add_header('Tags', tags)

        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.URLError:
            pass  # Silently fail - don't interrupt the main process

    @staticmethod
    def notify_url_complete(mix_name: str, current: int, total: int, success: bool, error: str = None):
        """Send notification when a URL finishes processing."""
        percent = int((current / total) * 100)
        progress = f"{percent}% complete ({current}/{total})"

        if success:
            title = "Setlist Complete"
            message = f"{mix_name}\n\nProgress: {progress}"
            tags = "white_check_mark"
        else:
            title = "Setlist Failed"
            message = f"{mix_name}\n\nProgress: {progress}"
            tags = "x"
            if error:
                message += f"\nError: {error[:100]}"

        Notifier.send(message, title, tags)

    @staticmethod
    def notify_batch_complete(results: list):
        """Send summary notification when all URLs are done."""
        success_count = sum(1 for _, status in results if status == "SUCCESS")
        total = len(results)

        title = "Batch Complete"
        message = f"Processed {success_count}/{total} URLs successfully"

        Notifier.send(message, title, tags="checkered_flag")
