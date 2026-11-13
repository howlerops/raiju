import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

spec = importlib.util.spec_from_file_location('preview_publish', Path(__file__).resolve().parents[1] / 'scripts/publish_preview_ui.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class PreviewPublicationTests(unittest.TestCase):
    def test_open_document_can_fetch_old_chunk_after_new_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            source, live = Path(folder) / 'dist', Path(folder) / 'live'
            (source / 'assets').mkdir(parents=True)
            (source / 'index.html').write_text('old document')
            (source / 'assets/old-hash.js').write_text('export const version = 1;')
            publisher.publish_ui(source, live)
            (source / 'assets/old-hash.js').unlink()
            (source / 'assets/new-hash.js').write_text('export const version = 2;')
            (source / 'index.html').write_text('new document')
            publisher.publish_ui(source, live)
            server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(live)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                origin = f'http://127.0.0.1:{server.server_port}'
                # These are the two different module URLs requested by old and new documents.
                with urlopen(origin + '/assets/old-hash.js') as old, urlopen(origin + '/assets/new-hash.js') as new:
                    self.assertNotEqual(old.read(), new.read())
                self.assertEqual((live / 'index.html').read_text(), 'new document')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_hash_collision_cannot_replace_open_tab_asset_or_publish_document(self):
        with tempfile.TemporaryDirectory() as folder:
            source, live = Path(folder) / 'dist', Path(folder) / 'live'
            (source / 'assets').mkdir(parents=True)
            (source / 'index.html').write_text('old document')
            (source / 'assets/immutable.js').write_text('old implementation')
            publisher.publish_ui(source, live)
            (source / 'assets/immutable.js').write_text('different implementation under same hash')
            (source / 'index.html').write_text('new document')
            with self.assertRaisesRegex(ValueError, 'Immutable asset collision'):
                publisher.publish_ui(source, live)
            self.assertEqual((live / 'assets/immutable.js').read_text(), 'old implementation')
            self.assertEqual((live / 'index.html').read_text(), 'old document')


if __name__ == '__main__':
    unittest.main()
