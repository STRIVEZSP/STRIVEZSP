import re
import os

readme_path = os.path.join(os.path.dirname(__file__), '../README.md')
apple_header = './assets/header_apple.svg'
google_header = './assets/header_google.svg'

def toggle_header():
    try:
        with open(readme_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check current header
        if apple_header in content:
            new_content = content.replace(apple_header, google_header)
            print(f"Switched header to Google style ({google_header})")
        elif google_header in content:
            new_content = content.replace(google_header, apple_header)
            print(f"Switched header to Apple style ({apple_header})")
        else:
            # If neither is found (or maybe the full path wasn't exact), try a regex or default to Apple
            print("Current header not recognized or already set. Resetting to Apple style.")
            # Simple replace if it matches the general structure, otherwise manual check needed.
            # Assuming the file has `src="..."` structure we can try to regex replace strictly the image source if needed.
            # But for now, let's just warning, or force Apple if we find *any* image tag? 
            # Safer to just look for the typical pattern if the simple replace failed.
            new_content = re.sub(r'src=["\'].*?header_.*?\.svg["\']', f'src="{apple_header}"', content)
            
            if new_content == content:
                 print("No header change made.")
                 return

        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

    except Exception as e:
        print(f"Error toggling header: {e}")

if __name__ == '__main__':
    toggle_header()
