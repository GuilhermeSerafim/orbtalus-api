"""
GeoRisk - Google Earth Engine Setup Script
Configures GEE authentication for MapBiomas integration
"""

import os
import sys


def setup_gee():
    """Configure Google Earth Engine authentication"""

    # Path to service account credentials
    credentials_path = os.path.join(os.path.dirname(__file__), "georisk-auth.json")

    if not os.path.exists(credentials_path):
        print("❌ Error: georisk-auth.json not found!")
        print(f"   Expected at: {credentials_path}")
        return False

    # Set environment variable for GEE authentication
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

    try:
        import ee
        from google.oauth2 import service_account

        # Load service account credentials
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=["https://www.googleapis.com/auth/earthengine"]
        )

        # Initialize Earth Engine with service account
        ee.Initialize(credentials=credentials)

        print("✅ Google Earth Engine initialized successfully!")
        print(f"   Using credentials: {credentials_path}")

        # Test connection
        try:
            # Try to access a simple asset to verify connection
            test_image = ee.Image("USGS/SRTMGL1_003")
            info = test_image.getInfo()
            print("✅ GEE connection verified!")
            return True
        except Exception as e:
            print(f"⚠️  Warning: GEE initialized but connection test failed: {e}")
            return True  # Still return True as initialization succeeded

    except ImportError:
        print("❌ Error: earthengine-api not installed!")
        print("   Run: pip install -r requirements.txt")
        return False
    except Exception as e:
        print(f"❌ Error initializing Google Earth Engine: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("GeoRisk - Google Earth Engine Setup")
    print("=" * 60)

    success = setup_gee()

    if success:
        print("\n✨ Setup complete! You can now use MapBiomas integration.")
        print("\nNext steps:")
        print("  1. Restart your server (uvicorn main:app --reload)")
        print("  2. Test the /risk endpoint")
        print("  3. Check logs for 'Google Earth Engine initialized successfully'")
        sys.exit(0)
    else:
        print("\n❌ Setup failed. Please check the errors above.")
        sys.exit(1)
