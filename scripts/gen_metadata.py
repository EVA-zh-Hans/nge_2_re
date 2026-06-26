"""
Generate metadata for patch builds.

This script collects:
1. Git commit hashes for the main repo and submodules
2. Translation statistics from ParaTranz API
3. Generates a JSON metadata file
4. Creates a 480x272 image displaying the metadata
"""

import json
import os
import subprocess
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from PIL import Image as PILImage


ROOT = Path(__file__).resolve().parents[1]
SOURCE_HAN_SANS_SC = ROOT / "resources" / "assets" / "font" / "SourceHanSansSC-Medium.otf"


def get_git_commit(repo_path: str = ".") -> str:
    """Get the current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def get_git_tags(repo_path: str = ".") -> list[str]:
    """Get all git tags that point at the current commit."""
    try:
        result = subprocess.run(
            ["git", "tag", "--points-at", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return [tag for tag in result.stdout.splitlines() if tag.strip()]
    except subprocess.CalledProcessError:
        return []


def get_submodule_commits() -> Dict[str, str]:
    """Get commit hashes for all submodules."""
    submodules = {}
    try:
        result = subprocess.run(
            ["git", "submodule", "status"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                # Format: " <commit> <path> (<description>)" or "-<commit> <path>"
                parts = line.strip().split()
                if len(parts) >= 2:
                    commit = parts[0].lstrip("-").lstrip("+")
                    path = parts[1]
                    submodules[path] = commit
    except subprocess.CalledProcessError:
        pass
    return submodules


def get_paratranz_leaderboard(
    project_id: int = 10882, auth_key: Optional[str] = None
) -> Optional[list]:
    """Get leaderboard data from ParaTranz API, filtering users with 0 contribution points."""
    if not auth_key:
        return None

    try:
        url = f"https://paratranz.cn/api/projects/{project_id}/leaderboard"
        headers = {"Authorization": auth_key}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        leaderboard_data = response.json()
        
        # Filter out users with 0 contribution points
        filtered_data = [
            user for user in leaderboard_data
            if user.get("points", 0) > 0
        ]
        
        return filtered_data
    except Exception as e:
        print(f"Warning: Failed to get ParaTranz leaderboard: {e}")
        return None


def get_paratranz_stats(
    project_id: int = 10882, auth_key: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get translation statistics from ParaTranz API."""
    if not auth_key:
        print("Warning: No AUTH_KEY provided, skipping ParaTranz stats")
        return None

    try:
        # Get project info
        url = f"https://paratranz.cn/api/projects/{project_id}"
        headers = {"Authorization": auth_key}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        project_data = response.json()

        # Get artifact info (latest build)
        artifacts_url = f"https://paratranz.cn/api/projects/{project_id}/artifacts"
        artifacts_response = requests.get(artifacts_url, headers=headers, timeout=10)
        artifacts_response.raise_for_status()
        artifacts_data = artifacts_response.json()

        # Combine data - artifacts API returns a single object or a list
        stats = {}
        latest_artifact = None
        
        if isinstance(artifacts_data, dict):
            # If it's a dict, use it directly
            latest_artifact = artifacts_data
        elif isinstance(artifacts_data, list) and len(artifacts_data) > 0:
            # If it's a list, get the first item
            latest_artifact = artifacts_data[0]
        
        if latest_artifact:
            stats = {
                "id": latest_artifact.get("id"),
                "createdAt": latest_artifact.get("createdAt"),
                "project": project_id,
                "total": latest_artifact.get("total", 0),
                "translated": latest_artifact.get("translated", 0),
                "disputed": latest_artifact.get("disputed", 0),
                "checked": latest_artifact.get("checked", 0),
                "reviewed": latest_artifact.get("reviewed", 0),
                "hidden": latest_artifact.get("hidden", 0),
                "size": latest_artifact.get("size", 0),
                "duration": latest_artifact.get("duration", 0),
            }
        else:
            # Fallback to project data
            stats = {
                "project": project_id,
                "name": project_data.get("name", ""),
                "total": project_data.get("total", 0),
                "translated": project_data.get("translated", 0),
                "disputed": project_data.get("disputed", 0),
                "reviewed": project_data.get("reviewed", 0),
            }

        return stats
    except Exception as e:
        print(f"Warning: Failed to get ParaTranz stats: {e}")
        return None


def generate_metadata(
    output_path: str, auth_key: Optional[str] = None
) -> Dict[str, Any]:
    """Generate complete metadata."""
    metadata = {
        "generated_at": datetime.now().isoformat(),
        "git": {
            "main_commit": get_git_commit(),
            "tags": get_git_tags(),
            "submodules": get_submodule_commits(),
        },
        "translation": get_paratranz_stats(auth_key=auth_key),
        "leaderboard": get_paratranz_leaderboard(auth_key=auth_key),
    }

    # Save to JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Metadata saved to: {output_path}")
    return metadata


def format_git_version(main_commit: str, tags: list[str]) -> str:
    """Format the repo version for display."""
    if tags:
        return ", ".join(tags)
    return main_commit[:8]


def download_avatar(avatar_url: str, size: int = 32) -> Any:
    """Download and resize avatar image."""
    try:
        from PIL import Image
        from io import BytesIO
        
        # Handle relative URLs from ParaTranz
        if avatar_url.startswith("/"):
            avatar_url = f"https://paratranz.cn{avatar_url}"
        
        response = requests.get(avatar_url, timeout=5)
        response.raise_for_status()
        avatar = Image.open(BytesIO(response.content))
        avatar = avatar.convert("RGBA")
        avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)
        return avatar
    except Exception as e:
        print(f"Warning: Failed to download avatar {avatar_url}: {e}")
        return None


def save_raw_rgba8888(img: Any, output_path: str):
    """Save image as raw RGBA8888 binary data for PSP."""
    try:
        import struct
        
        # Ensure image is in RGBA mode
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Get pixel data
        pixels = img.load()
        width, height = img.size
        
        # Write raw RGBA8888 data
        with open(output_path, 'wb') as f:
            for y in range(height):
                for x in range(width):
                    r, g, b, a = pixels[x, y]
                    # PSP uses ABGR8888 format in memory
                    # Pack as 32-bit unsigned integer: AABBGGRR
                    pixel = struct.pack('<I', (a << 24) | (b << 16) | (g << 8) | r)
                    f.write(pixel)
    except Exception as e:
        print(f"Warning: Failed to save raw RGBA8888: {e}")


def generate_metadata_image(metadata: Dict[str, Any], output_path: str):
    """Generate a 480x272 fullscreen image displaying all contributors with avatars."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Warning: Pillow not installed, skipping image generation")
        return

    # Create fullscreen image
    width, height = 480, 272
    background_color = (30, 30, 40, 255)  # Solid dark background
    text_color = (255, 255, 255)
    accent_color = (100, 180, 255)
    header_bg = (20, 20, 30, 255)

    img = Image.new("RGBA", (width, height), background_color)
    draw = ImageDraw.Draw(img)

    # Load fonts
    try:
        font_paths = [
            str(SOURCE_HAN_SANS_SC),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "C:\\Windows\\Fonts\\SimSun.ttc",
        ]
        font_title = None
        for font_path in font_paths:
            try:
                font_title = ImageFont.truetype(font_path, 16)
                break
            except (OSError, IOError):
                continue
        
        if font_title is None:
            raise OSError("No truetype fonts found")
            
        font_medium = ImageFont.truetype(font_title.path, 11)
        font_small = ImageFont.truetype(font_title.path, 9)
    except (OSError, IOError):
        font_title = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Draw header section
    header_height = 55
    draw.rectangle([0, 0, width, header_height], fill=header_bg)
    
    # Title
    title = "新世纪福音战士 2 被创造的世界 汉化补丁 - 贡献者名单"
    draw.text((10, 5), title, fill=accent_color, font=font_title)
    
    # Stats line
    stats_y = 28
    tags = metadata["git"].get("tags", [])
    repo_version = format_git_version(metadata["git"]["main_commit"], tags)
    draw.text((10, stats_y), f"主仓库版本: {repo_version}", fill=text_color, font=font_small)
    
    # Submodule versions: only resources/trans_pic
    submodules = metadata["git"]["submodules"]
    if "resources/trans_pic" in submodules:
        trans_pic_commit = submodules["resources/trans_pic"][:8]
        draw.text((120, stats_y), f"图片仓库版本: {trans_pic_commit}", fill=text_color, font=font_small)
    
    if metadata.get("translation"):
        trans = metadata["translation"]
        total = trans.get("total", 0)
        translated = trans.get("translated", 0)
        if total > 0:
            translated_percent = (translated / total) * 100
            draw.text((240, stats_y), f"翻译: {translated}/{total} ({translated_percent:.1f}%)", 
                     fill=text_color, font=font_small)
        # Review stats
        reviewed = trans.get("reviewed", 0)
        if total > 0 and reviewed > 0:
            review_percent = (reviewed / total) * 100
            draw.text((360, stats_y), f"审核: {reviewed}/{total} ({review_percent:.1f}%)", 
                     fill=text_color, font=font_small)
    
    # Generation time
    gen_time = metadata["generated_at"]
    try:
        dt = datetime.fromisoformat(gen_time)
        # UTF+8 timezone conversion
        dt = dt + timedelta(hours=8)
        time_str = dt.strftime("%m-%d %H:%M")
    except (ValueError, AttributeError):
        time_str = gen_time
    draw.text((10, stats_y + 12), f"生成: {time_str}", fill=(180, 180, 180), font=font_small)

    # Draw contributors section
    if metadata.get("leaderboard") and len(metadata["leaderboard"]) > 0:
        contributors = metadata["leaderboard"]
        
        # Layout settings
        avatar_size = 24
        row_height = 28
        start_y = header_height + 8
        start_x = 5
        column_width = 160  # Increased number of columns to 3

        for idx, user in enumerate(contributors):
            # Calculate position (3 columns)
            col = idx % 3  # Adjusted for 3 columns
            row = idx // 3

            x = start_x + col * column_width
            y = start_y + row * row_height

            # Stop if we run out of vertical space (leave room for footer)
            if y + row_height > height - 35:
                break

            # Download and draw avatar
            avatar_url = user.get("avatar", "")
            avatar = None
            if avatar_url:
                avatar = download_avatar(avatar_url, avatar_size)

            avatar_x = x + 2
            avatar_y = y + 2

            if avatar:
                img.paste(avatar, (avatar_x, avatar_y), avatar)
            else:
                # Draw placeholder circle
                draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size],
                           fill=(60, 60, 70))

            # Text position (next to avatar)
            text_x = avatar_x + avatar_size + 5

            # Nickname
            nickname = user.get("nickname") or user.get("username", "Unknown")
            draw.text((text_x, y + 2), f"{nickname}", fill=text_color, font=font_medium)

            # Contribution stats
            translated = user.get("translated", 0)
            edited = user.get("edited", 0)
            reviewed = user.get("reviewed", 0)
            points = user.get("points", 0)

            stats_text = f"翻{translated} 编{edited} 审{reviewed} ({points:.0f}pt)"
            draw.text((text_x, y + 14), stats_text, fill=(200, 200, 200), font=font_small)

    # Draw footer watermark
    footer_y = height - 35
    draw.text((10, footer_y), "EVA2 汉化计划", fill=accent_color, font=font_medium)
    draw.text((10, footer_y + 14), "数据来自 ParaTranz | 感谢 ParaTranz 平台支持", 
             fill=(150, 150, 150), font=font_small)

    # Save image
    img.save(output_path)
    print(f"Metadata image saved to: {output_path}")
    
    # Save raw RGBA8888 binary for PSP plugin
    raw_output_path = output_path.replace('.png', '.raw')
    save_raw_rgba8888(img, raw_output_path)
    print(f"Raw RGBA8888 image saved to: {raw_output_path}")


def generate_metadata_pic0(metadata: Dict[str, Any], output_path: str):
    """Generate a 310x180 small image displaying metadata with text in bottom-right corner."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Warning: Pillow not installed, skipping PIC0 generation")
        return

    # Create image with RGBA for transparency
    width, height = 310, 180
    background_color = (30, 30, 40, 0)  # Transparent
    text_color = (255, 255, 255)
    accent_color = (100, 180, 255)
    box_color = (30, 30, 40, 200)  # Semi-transparent background box

    img = Image.new("RGBA", (width, height), background_color)
    draw = ImageDraw.Draw(img)

    # Try to use a default font, fallback to default if not available
    try:
        # Try common font paths across different systems with CJK support
        font_paths = [
            str(SOURCE_HAN_SANS_SC),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Noto Sans CJK
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Fallback
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "C:\\Windows\\Fonts\\SimSun.ttc",  # Windows
        ]
        font_large = None
        for font_path in font_paths:
            try:
                font_large = ImageFont.truetype(font_path, 14)
                break
            except (OSError, IOError):
                continue
        
        if font_large is None:
            raise OSError("No truetype fonts found")
            
        font_medium = ImageFont.truetype(font_large.path, 11)
        font_small = ImageFont.truetype(font_large.path, 10)
    except (OSError, IOError):
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # First pass: collect all text lines
    lines = []
    
    # Title
    lines.append(("补丁信息 EVA2 汉化计划", font_large, accent_color))

    # Commit info
    tags = metadata["git"].get("tags", [])
    repo_version = format_git_version(metadata["git"]["main_commit"], tags)
    lines.append((f"主仓库: {repo_version}", font_small, text_color))
    
    # Submodules
    for path, commit in metadata["git"]["submodules"].items():
        lines.append((f"  {path}: {commit[:8]}", font_small, text_color))

    # Translation stats summary
    if metadata.get("translation"):
        trans = metadata["translation"]
        total = trans.get("total", 0)
        translated = trans.get("translated", 0)
        reviewed = trans.get("reviewed", 0)

        if total > 0:
            translated_percent = (translated / total) * 100
            lines.append((f"翻译: {translated}/{total}", font_small, text_color))
            lines.append((f"进度 {translated_percent:.1f}%", font_small, accent_color))
            
            if reviewed > 0:
                review_percent = (reviewed / total) * 100
                lines.append((f"审核: {review_percent:.1f}%", font_small, text_color))

    # Translation data creation time (convert from UTC to China timezone UTC+8)
    time_str = "unknown"
    if metadata.get("translation") and "createdAt" in metadata["translation"]:
        try:
            dt = datetime.fromisoformat(metadata["translation"]["createdAt"].replace("Z", "+00:00"))
            # Convert to China timezone (UTC+8)
            dt = dt + timedelta(hours=8)
            time_str = dt.strftime("%m-%d %H:%M")
        except (ValueError, AttributeError):
            time_str = "unknown"
    lines.append((f"数据: {time_str}", font_small, (150, 150, 150)))

    # Calculate dimensions
    line_heights = []
    max_width = 0
    
    for text, font, _ in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        line_heights.append(text_height)
        max_width = max(max_width, text_width)

    # Calculate total height with spacing
    line_spacing = 3
    total_text_height = sum(line_heights) + len(lines) * line_spacing - line_spacing

    # Add padding
    padding = 10
    box_width = width - padding * 2  # Use full width
    box_height = total_text_height + padding * 2

    # Position at top-left to fill the image
    box_left = padding
    box_top = padding
    box_right = width - padding
    box_bottom = box_top + box_height

    # Ensure box doesn't exceed image bounds
    if box_bottom > height:
        box_bottom = height - padding

    # Draw semi-transparent background box
    draw.rectangle([box_left, box_top, box_right, box_bottom], fill=box_color)

    # Draw text lines
    y = box_top + padding
    for (text, font, color), line_height in zip(lines, line_heights):
        draw.text((box_left + padding, y), text, fill=color, font=font)
        y += line_height + line_spacing

    # Save image
    img.save(output_path)
    print(f"PIC0 image saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate patch metadata")
    parser.add_argument(
        "--output",
        default="build/metadata.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "--image",
        default="build/metadata.png",
        help="Output image file path",
    )
    parser.add_argument(
        "--pic0",
        default="build/PIC0.png",
        help="Output PIC0 image file path (310x180)",
    )
    parser.add_argument(
        "--auth-key",
        help="ParaTranz auth key (or use AUTH_KEY env var)",
    )

    args = parser.parse_args()

    # Get auth key from args or environment
    auth_key = args.auth_key or os.getenv("AUTH_KEY")

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.image).parent.mkdir(parents=True, exist_ok=True)
    Path(args.pic0).parent.mkdir(parents=True, exist_ok=True)

    # Generate metadata
    metadata = generate_metadata(args.output, auth_key=auth_key)

    # Generate images
    generate_metadata_image(metadata, args.image)
    generate_metadata_pic0(metadata, args.pic0)

    print("\nMetadata generation complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
