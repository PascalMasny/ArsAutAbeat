"""WebSocket session handler for the gallery installation."""

import asyncio
import json
import time
from typing import Optional

from fastapi import WebSocket

from core.state_machine import InstallationState, advance_state, elapsed
from vision.camera import GalleryProcessor, CameraState
from catalog.manager import get_catalog_manager
from data.db import get_session
from config import (
    ATTRACT_CYCLE_S, ATTRACT_DURATION_S, FRAME_COUNT,
    BASELINE_DURATION, GALLERY_DURATION, REVEAL_DURATION,
)

# ── Singletons shared across all WebSocket connections ───────────────────────
# One processor: analysis thread and MediaPipe models start once at server
# startup, before any visitor connects, so there is no cold-start lag.
# One state: reconnects (page refresh, brief disconnect) resume mid-session.

_processor: Optional[GalleryProcessor] = None
_state: Optional[InstallationState] = None
_catalog = None


def get_processor() -> GalleryProcessor:
    global _processor
    if _processor is None:
        _processor = GalleryProcessor()
    return _processor


def get_installation_state() -> InstallationState:
    global _state
    if _state is None:
        _state = InstallationState()
    return _state


def get_catalog():
    global _catalog
    if _catalog is None:
        _catalog = get_catalog_manager()
    return _catalog


class GallerySession:
    def __init__(self, websocket: WebSocket):
        self._ws = websocket
        self._state = get_installation_state()
        self._processor = get_processor()
        self._catalog = get_catalog()
        self._last_state_json: str = ""

    async def run(self):
        await self._ws.accept()
        await self._push_state()

        while True:
            try:
                msg = await asyncio.wait_for(self._ws.receive(), timeout=2.0)
            except asyncio.TimeoutError:
                await self._tick(None)
                continue

            if msg["type"] == "websocket.disconnect":
                break
            if msg["type"] == "websocket.receive":
                data = msg.get("bytes")
                if data:
                    await self._tick(data)

    def cleanup(self):
        # Processor is a singleton — do not stop it on disconnect.
        pass

    async def _tick(self, jpeg_bytes: Optional[bytes]):
        if jpeg_bytes:
            self._processor.push_frame(jpeg_bytes)

        camera_state = self._processor.get_state()

        phase = self._state.phase
        self._processor.set_emotion_sampling(phase in ("BASELINE", "GALLERY"))
        self._processor.set_pose_sampling(phase == "IDLE")

        db = get_session()
        try:
            advance_state(self._state, camera_state, self._catalog, db)
        finally:
            db.close()

        await self._push_state(camera_state)

    async def _push_state(self, camera_state: Optional[CameraState] = None):
        payload = self._build_payload(camera_state)
        serialized = json.dumps(payload)
        if serialized != self._last_state_json:
            self._last_state_json = serialized
            await self._ws.send_text(serialized)

    def _build_payload(self, camera_state: Optional[CameraState]) -> dict:
        state = self._state
        phase = state.phase
        t = elapsed(state)

        emotions: dict = {}
        face_present = False
        hands_raised = False
        if camera_state:
            emotions = camera_state.latest_emotions
            face_present = camera_state.face_present
            hands_raised = camera_state.hands_raised

        elapsed_idle = time.time() - state.phase_entered_at
        show_attract = (phase == "IDLE") and (int(elapsed_idle) % ATTRACT_CYCLE_S < ATTRACT_DURATION_S)

        attract_graph_b64 = None
        soul_count = 0
        if show_attract:
            db = get_session()
            try:
                from data.models import Viewing
                soul_count = db.query(Viewing).count()
            finally:
                db.close()

            if soul_count != state.attract_viewing_count:
                from backend.graphs import attract_graph
                db2 = get_session()
                try:
                    state.attract_graph_b64 = attract_graph(db2)
                finally:
                    db2.close()
                state.attract_viewing_count = soul_count

            attract_graph_b64 = state.attract_graph_b64

        artwork = None
        if state.current_artwork:
            a = state.current_artwork
            artwork = {
                "slug":         a["slug"],
                "title":        a["title"],
                "artist":       a.get("artist", ""),
                "total_frames": FRAME_COUNT,
                "frame_ext":    a.get("frame_ext", ".jpg"),
            }

        collective = None
        if state.collective_data:
            c = state.collective_data
            collective = {
                "soul_count":     c.get("count", 0),
                "dominant_latin": c.get("dominant_latin", ""),
                "verdict":        c.get("verdict", ""),
                "concordance":    c.get("concordance", 0.0),
            }

        return {
            "show_mode":       state.show_mode,
            "phase":           phase,
            "phase_elapsed":   round(t, 2),
            "phase_duration":  {
                "BASELINE": BASELINE_DURATION,
                "GALLERY":  GALLERY_DURATION,
                "REVEAL":   REVEAL_DURATION,
            }.get(phase, 0.0),
            "phase_started_at": state.phase_entered_at,
            "attract_mode":    show_attract,
            "soul_count":      soul_count,
            "emotions":        emotions,
            "face_present":    face_present,
            "hands_raised":    hands_raised,
            "artwork":         artwork,
            "verdict":         state.personal_verdict,
            "personal_lines":  state.personal_lines,
            "breaking_index":  state.breaking_index,
            "deviations":      [round(d, 4) for d in state.deviations],
            "collective":      collective,
            "attract_graph":   attract_graph_b64,
        }
