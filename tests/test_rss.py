import sys
import os
# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import io
import pytest
from PIL import Image
from local import download_image

class DummyResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception("HTTP Error")

def dummy_requests_get(url, timeout):
    # Create a simple 100x100 image in memory.
    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return DummyResponse(buf.getvalue())

def test_download_image(monkeypatch, tmp_path):
    # Override requests.get in the local module with our dummy function.
    monkeypatch.setattr("local.requests.get", dummy_requests_get)
    
    # Create a temporary directory for images.
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    
    # Attempt to download an image.
    image_path = download_image("http://example.com/image.jpg", image_dir=str(image_dir))
    assert image_path is not None, "Image download should return a valid file path."
    
    # Check that the downloaded file exists.
    downloaded_file = image_dir / os.path.basename(image_path)
    assert downloaded_file.exists(), "Downloaded image file should exist."
