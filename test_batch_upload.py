#!/usr/bin/env python3
"""
Test script for Base64 batch upload endpoint.
Tests the /api/upload/mobile/batch endpoint with real images.
"""

import requests
import json
import base64
from PIL import Image, ImageDraw, ImageFont
import io
import sys


def create_test_image(text: str, size=(800, 600)) -> bytes:
    """Create a simple test image with text."""
    img = Image.new('RGB', size, color='white')
    draw = ImageDraw.Draw(img)
    
    # Draw some text
    try:
        # Try to use a nicer font if available
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    except:
        # Fallback to default font
        font = ImageFont.load_default()
    
    # Calculate text position (centered)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    position = ((size[0] - text_width) // 2, (size[1] - text_height) // 2)
    
    draw.text(position, text, fill='black', font=font)
    
    # Add some decorative elements
    draw.rectangle([20, 20, size[0]-20, size[1]-20], outline='blue', width=3)
    
    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG', quality=85)
    return img_bytes.getvalue()


def test_batch_upload(server_url: str, num_images: int = 3):
    """
    Test the batch upload endpoint.
    
    Args:
        server_url: Base URL of the server (e.g., http://192.168.1.218)
        num_images: Number of test images to upload (1-50)
    """
    print(f"{'='*80}")
    print(f"Testing Base64 Batch Upload Endpoint")
    print(f"{'='*80}")
    print(f"Server: {server_url}")
    print(f"Images to upload: {num_images}")
    print()
    
    # Create test images
    print("📸 Creating test images...")
    images_b64 = []
    filenames = []
    
    for i in range(num_images):
        print(f"  Creating image {i+1}/{num_images}...", end=' ')
        
        # Create image with page number
        img_bytes = create_test_image(f"Page {i+1}\nTest Image", size=(800, 600))
        
        # Encode to Base64
        b64_data = base64.b64encode(img_bytes).decode('utf-8')
        images_b64.append(b64_data)
        filenames.append(f"test_page_{i+1:03d}.jpg")
        
        print(f"✓ ({len(img_bytes)} bytes → {len(b64_data)} bytes Base64)")
    
    print(f"\n✅ Created {num_images} test images")
    print()
    
    # Prepare payload
    payload = {
        "images": images_b64,
        "filenames": filenames
    }
    
    payload_size = len(json.dumps(payload))
    print(f"📦 Payload size: {payload_size:,} bytes ({payload_size / 1024:.1f} KB)")
    print()
    
    # Test both iPhone string format and proper array format
    endpoint = f"{server_url}/api/upload/mobile/batch"

    # First test: iPhone Shortcuts format (newline-separated strings)
    if num_images > 1:
        print(f"🧪 Testing iPhone Shortcuts Format (newline-separated strings)")
        print(f"   (This is how iPhone Shortcuts sends multiple items)")
        print(f"🚀 Sending POST request to: {endpoint}")
        print()

        # iPhone Shortcuts concatenates with newlines
        iphone_payload = {
            "images": "\n".join(payload["images"]),  # Newline-separated Base64 strings
            "filenames": "\n".join(payload["filenames"])  # Newline-separated filenames
        }

        try:
            response = requests.post(
                endpoint,
                headers={'Content-Type': 'application/json'},
                json=iphone_payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                print(f"✅ iPhone Shortcuts format works!")
                print(f"   Server split string into {result.get('image_count')} images")
                print()
            else:
                print(f"❌ iPhone format failed: {response.json()}")
                print()
        except Exception as e:
            print(f"⚠️  iPhone format test error: {e}")
            print()

    # Main test: Array format (correct format)
    print(f"🚀 Sending POST request to: {endpoint}")
    print()

    try:
        response = requests.post(
            endpoint,
            headers={'Content-Type': 'application/json'},
            json=payload,
            timeout=30
        )
        
        print(f"{'='*80}")
        print(f"Response Status: {response.status_code}")
        print(f"{'='*80}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ SUCCESS!")
            print()
            print("Response:")
            print(json.dumps(result, indent=2))
            print()
            print(f"📄 Created Opinion: #{result.get('opinion_id')}")
            print(f"📄 Created Document: #{result.get('document_id')}")
            print(f"🖼️  Images combined: {result.get('image_count')}")
            print(f"🔍 OCR queued: {result.get('ocr_queued')}")
            print(f"🔗 Preview URL: {server_url}{result.get('preview_url')}")
            print()
            print(f"{'='*80}")
            print("✅ TEST PASSED")
            print(f"{'='*80}")
            return True
            
        else:
            print("❌ FAILED!")
            print()
            try:
                error = response.json()
                print("Error details:")
                print(json.dumps(error, indent=2))
            except:
                print(f"Response text: {response.text}")
            print()
            print(f"{'='*80}")
            print("❌ TEST FAILED")
            print(f"{'='*80}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ CONNECTION ERROR!")
        print(f"   Could not connect to {server_url}")
        print("   Make sure:")
        print("   - Server is running")
        print("   - URL is correct")
        print("   - You're on the same network")
        print()
        print(f"{'='*80}")
        print("❌ TEST FAILED")
        print(f"{'='*80}")
        return False
        
    except requests.exceptions.Timeout:
        print("❌ TIMEOUT!")
        print(f"   Request took longer than 30 seconds")
        print()
        print(f"{'='*80}")
        print("❌ TEST FAILED")
        print(f"{'='*80}")
        return False
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        print()
        print(f"{'='*80}")
        print("❌ TEST FAILED")
        print(f"{'='*80}")
        return False


def main():
    """Main test function."""
    # Default server URL
    server_url = "http://localhost:80"
    num_images = 3
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        server_url = sys.argv[1]
    
    if len(sys.argv) > 2:
        try:
            num_images = int(sys.argv[2])
            if num_images < 1 or num_images > 50:
                print("❌ Number of images must be between 1 and 50")
                sys.exit(1)
        except ValueError:
            print("❌ Invalid number of images")
            sys.exit(1)
    
    # Run test
    success = test_batch_upload(server_url, num_images)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    print()
    print("Base64 Batch Upload Test Script")
    print("=" * 80)
    print()
    print("Usage: python test_batch_upload.py [SERVER_URL] [NUM_IMAGES]")
    print()
    print("Examples:")
    print("  python test_batch_upload.py")
    print("  python test_batch_upload.py http://192.168.1.100")
    print("  python test_batch_upload.py http://192.168.1.100 5")
    print()
    print("=" * 80)
    print()
    
    main()
