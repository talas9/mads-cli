"""mads creative command group — Meta Marketing API Ad Creative management.

KB reference: kb/marketing-api.md (relative to mads-cli root)
Endpoints: POST act_{ad_account_id}/adimages, POST act_{ad_account_id}/advideos,
POST act_{ad_account_id}/adcreatives
Uses mads_lib.http.graph_request() for every call — JSON body for `create`,
multipart/form-data (via graph_request's `files=` kwarg) for the two upload
commands. See campaigns.py's module docstring for the overall shape/logging
convention this file follows.

Per the task shape for this group, `creative` intentionally does NOT get the
list/status/budget/delete commands the other three resource groups get —
only create + the two binary-upload commands (an AdCreative is an
assemble-once, reference-by-id object; status/delete would touch the KB's
`Status enum: ACTIVE, DELETED, IN_PROCESS, WITH_ISSUES` if ever added).
"""
import json
import os
from pathlib import Path

import click

from .config import AD_ACCOUNT_ID
from .db import get_db
from .http import graph_request
from .output import print_error, print_json
from .timeutil import now_local

# KB § Field Reference — Ad Creative — CallToActionType enum (100+ values,
# SDK-confirmed fetched 2026-07-01 from facebook_business/adobjects/adcreative.py).
_CALL_TO_ACTION_TYPES = (
    "ADD_TO_CART", "APPLY_NOW", "ASK_ABOUT_SERVICES", "ASK_A_QUESTION", "ASK_FOR_MORE_INFO", "ASK_US",
    "AUDIO_CALL", "BOOK_A_CONSULTATION", "BOOK_NOW", "BOOK_TRAVEL", "BROWSE_SHOP", "BUY", "BUY_NOW",
    "BUY_TICKETS", "BUY_VIA_MESSAGE", "CALL", "CALL_ME", "CALL_NOW", "CHAT_NOW", "CHAT_WITH_US",
    "CONFIRM", "CONTACT", "CONTACT_US", "DONATE", "DONATE_NOW", "DOWNLOAD", "EVENT_RSVP",
    "FIND_A_GROUP", "FIND_OUT_MORE", "FIND_YOUR_GROUPS", "FOLLOW_NEWS_STORYLINE", "FOLLOW_PAGE",
    "FOLLOW_USER", "GET_A_QUOTE", "GET_DETAILS", "GET_DIRECTIONS", "GET_IN_TOUCH", "GET_OFFER",
    "GET_OFFER_VIEW", "GET_PROMOTIONS", "GET_QUOTE", "GET_SHOWTIMES", "GET_STARTED", "INQUIRE_NOW",
    "INSTALL_APP", "INSTALL_MOBILE_APP", "JOIN_CHANNEL", "JOIN_LIVE_VIDEO", "LEARN_MORE", "LIKE_PAGE",
    "LISTEN_MUSIC", "LISTEN_NOW", "MAKE_AN_APPOINTMENT", "MESSAGE_PAGE", "MOBILE_DOWNLOAD",
    "NO_BUTTON", "OPEN_INSTANT_APP", "OPEN_LINK", "ORDER_NOW", "PAY_TO_ACCESS", "PLAY_GAME",
    "PLAY_GAME_ON_FACEBOOK", "PURCHASE_GIFT_CARDS", "RAISE_MONEY", "RECORD_NOW", "REFER_FRIENDS",
    "REQUEST_TIME", "SAY_THANKS", "SEE_MORE", "SEE_SHOP", "SELL_NOW", "SEND_A_GIFT",
    "SEND_GIFT_MONEY", "SEND_UPDATES", "SHARE", "SHOP_NOW", "SHOP_WITH_AI", "SIGN_UP",
    "SOTTO_SUBSCRIBE", "START_A_CHAT", "START_ORDER", "SUBSCRIBE", "SWIPE_UP_PRODUCT",
    "SWIPE_UP_SHOP", "TRY_DEMO", "TRY_ON_WITH_AI", "UPDATE_APP", "USE_APP", "USE_MOBILE_APP",
    "VIDEO_ANNOTATION", "VIDEO_CALL", "VIEW_CART", "VIEW_CHANNEL", "VIEW_IN_CART", "VIEW_PRODUCT",
    "VISIT_PAGES_FEED", "VISIT_WEBSITE", "WATCH_LIVE_VIDEO", "WATCH_MORE", "WATCH_VIDEO",
    "WHATSAPP_MESSAGE", "WOODHENGE_SUPPORT",
)


@click.group()
def creative():
    """Ad Creative management (image/video upload + creative assembly)."""
    pass


# ── Helpers (duplicated per resource-group module — see campaigns.py) ───────


def _act_id(ad_account_id=None):
    aid = (ad_account_id or AD_ACCOUNT_ID or "").strip()
    if not aid:
        return None
    return aid if aid.startswith("act_") else f"act_{aid}"


def _require_act_id(ad_account_id, as_json):
    act = _act_id(ad_account_id)
    if not act:
        raise SystemExit(print_error(
            "META_AD_ACCOUNT_ID is not set (or pass --ad-account-id).",
            code="VALIDATION", as_json=as_json,
        ))
    return act


def _confirm_and_log(action, details, dry_run=False, yes=False):
    if dry_run:
        click.secho(f"  DRY RUN: {action} — {details}", fg="yellow")
        return False
    if not yes:
        click.confirm(f"  Execute: {action}?", abort=True)
    return True


def _auto_log(action, details, campaign_name="", campaign_id=""):
    """Best-effort changelog write; never raises (mirrors mads_lib.cli._auto_log).

    Note: `get_db()` raises `SystemExit(1)` (not a plain `Exception`) when
    MADS_DB_PATH doesn't exist yet — caught explicitly here alongside
    `Exception` so a missing/not-yet-initialized DB never aborts an otherwise
    successful mutation.
    """
    try:
        conn = get_db()
        ts = now_local()
        raw = {
            "timestamp": ts, "action": action, "details": details,
            "campaign": campaign_name, "campaign_id": campaign_id, "agent": "mads-cli",
        }
        conn.execute(
            "INSERT INTO changelog (timestamp, action, campaign, campaign_id, details, "
            "reason, agent, snapshot_ref, script, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, action, campaign_name, campaign_id, details, "", "mads-cli", "", "", json.dumps(raw)),
        )
        conn.commit()
        conn.close()
    except (Exception, SystemExit):
        pass


# ── Commands ─────────────────────────────────────────────────


@creative.command("upload-image")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--ad-account-id", default=None)
@click.option("--json", "as_json", is_flag=True)
def creative_upload_image(file_path, ad_account_id, as_json):
    """Upload a local image and print its image_hash (for AdCreative.image_hash).

    KB: kb/marketing-api.md § DG-4 — POST act_{ad_account_id}/adimages
    (multipart/form-data). The full `adimages` field/response table is out of
    scope for this KB — this command implements Meta's standard, widely
    documented `{"images": {"<name>": {"hash": ...}}}` response shape;
    (unverified in this KB) — confirm against a real upload before scripting
    tightly around the response shape.
    """
    act = _require_act_id(ad_account_id, as_json)
    path = Path(file_path)
    with open(path, "rb") as f:
        files = {path.name: (path.name, f.read())}
    result = graph_request("POST", f"{act}/adimages", files=files, as_json=as_json)
    _auto_log("creative_upload_image", str(path))
    if as_json:
        print_json(result)
        return
    images = result.get("images", {}) if isinstance(result, dict) else {}
    entry = images.get(path.name, {})
    image_hash = entry.get("hash", "")
    if image_hash:
        click.secho(f"✓ Uploaded {path.name} → image_hash {image_hash}", fg="green")
    else:
        click.secho(f"⚠ Uploaded {path.name} but could not find a hash in the response — full response below:", fg="yellow")
        print_json(result)


@creative.command("upload-video")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--ad-account-id", default=None)
@click.option("--json", "as_json", is_flag=True)
def creative_upload_video(file_path, ad_account_id, as_json):
    """Upload a local video and print its video_id (for AdCreative.video_id).

    KB: kb/marketing-api.md § DG-4 — POST act_{ad_account_id}/advideos
    (multipart/form-data, `source` field). This is a simple single-request
    upload — Meta's resumable/chunked protocol for large files is out of
    scope here, and the `advideos` field table itself is flagged (unverified)
    in the KB; verify empirically for large/slow files.
    """
    act = _require_act_id(ad_account_id, as_json)
    path = Path(file_path)
    with open(path, "rb") as f:
        files = {"source": (path.name, f.read())}
    result = graph_request("POST", f"{act}/advideos", files=files, as_json=as_json)
    _auto_log("creative_upload_video", str(path))
    if as_json:
        print_json(result)
        return
    video_id = result.get("id", "") if isinstance(result, dict) else ""
    if video_id:
        click.secho(f"✓ Uploaded {path.name} → video_id {video_id}", fg="green")
    else:
        click.secho(f"⚠ Uploaded {path.name} but could not find an id in the response — full response below:", fg="yellow")
        print_json(result)


@creative.command("create")
@click.argument("name")
@click.option("--page-id", default=lambda: os.environ.get("META_PAGE_ID", ""),
              help="Facebook Page ID behind the ad (falls back to $META_PAGE_ID).")
@click.option("--link", required=True, help="Landing page URL (include any tracking/?branch= query params).")
@click.option("--message", default="", help="Primary ad body text (link_data.message / video_data.message).")
@click.option("--description", default="", help="Secondary description line (link_data.description).")
@click.option("--headline", default="", help="Link headline (link_data.name).")
@click.option("--image-hash", default=None, help="From `mads creative upload-image` — builds a link/image creative.")
@click.option("--video-id", default=None, help="From `mads creative upload-video` — builds a video creative instead of a link/image one.")
@click.option("--thumbnail-hash", default=None, help="Video thumbnail image_hash (video_data.image_hash) — only used with --video-id.")
@click.option("--cta-type", type=click.Choice(_CALL_TO_ACTION_TYPES), default="SHOP_NOW", help="call_to_action.type.")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def creative_create(name, page_id, link, message, description, headline, image_hash, video_id,
                     thumbnail_hash, cta_type, ad_account_id, dry_run, yes, as_json):
    """Create an AdCreative (link/image or video) via object_story_spec.

    KB: kb/marketing-api.md § 3. Create Ad Creative; § DG-4 Ad Creative Deep
    Dive — POST act_{ad_account_id}/adcreatives. Gotcha #9: AdCreative fields
    are almost entirely spec objects — even a "simple" text/image ad nests
    through object_story_spec.link_data.
    """
    if not page_id:
        raise SystemExit(print_error(
            "No Page ID — pass --page-id or set META_PAGE_ID.", code="VALIDATION", as_json=as_json,
        ))

    act = _require_act_id(ad_account_id, as_json)
    call_to_action = {"type": cta_type, "value": {"link": link}}

    object_story_spec = {"page_id": page_id}
    if video_id:
        video_data = {"video_id": video_id, "call_to_action": call_to_action}
        if message:
            video_data["message"] = message
        if thumbnail_hash:
            video_data["image_hash"] = thumbnail_hash
        object_story_spec["video_data"] = video_data
    else:
        link_data = {"link": link, "call_to_action": call_to_action}
        if message:
            link_data["message"] = message
        if description:
            link_data["description"] = description
        if headline:
            link_data["name"] = headline
        if image_hash:
            link_data["image_hash"] = image_hash
        object_story_spec["link_data"] = link_data

    body = {"name": name, "object_story_spec": object_story_spec}

    if not _confirm_and_log(f"create ad creative '{name}'", json.dumps(body), dry_run, yes):
        return

    result = graph_request("POST", f"{act}/adcreatives", json_body=body, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("creative_create", f"'{name}' page={page_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created ad creative '{name}' → id {new_id or '?'}", fg="green")
