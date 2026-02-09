"""
Conversation Manager - Session History & Personalization for Gemini 3

Manages rolling conversation history for multi-turn Gemini 3 Flash interactions.
Supports:
- Full session history (entire session until 5-min silence timeout)
- Dynamic system instruction composed from user profile
- Personal fact extraction ("my name is...", "remember that...")
- Context-aware response length limits
- SQLite persistence for session recovery and analytics

Author: Haziq (@IRSPlays) + AI Implementer (Claude)
Date: February 7, 2026
Project: Cortex v2.0 - YIA 2026
"""

import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default system instruction (overridden by personalization if available)
DEFAULT_SYSTEM_INSTRUCTION = (
    "You are Cortex, a personal AI assistant for a visually impaired user "
    "wearing smart glasses with a camera. Be specific about positions "
    "(left, right, ahead), distances, colors, text on signs, and hazards. "
    "Speak naturally and refer to past conversation when relevant.\n\n"
    "SPATIAL GUIDANCE: When the user asks where an object is and you cannot "
    "see it in the current camera frame, guide them to search by suggesting "
    "they turn left, right, or look around. After they adjust, check again "
    "and tell them whether you can see it now. Use your memory of past "
    "observations to suggest which room or direction the object might be in.\n\n"
    "DETAILED OBSERVATION: When describing scenes, note environmental details "
    "like wall color, room type, furniture, landmarks, and any text visible. "
    "These details help you remember locations across conversations. If the "
    "user asks about an object you saw before in a different room, use those "
    "visual clues to guide them back (e.g., 'Your keyboard was on a desk in "
    "what looked like a bedroom with blue walls. You seem to be in the kitchen "
    "now, so try heading to your bedroom.').\n\n"
    "OBJECT RECALL: When the user asks where an object is (e.g., 'where is my wallet?'), "
    "you may receive historical reference images tagged [Historical observation] alongside "
    "the current camera view. Study these historical images carefully - note the room type, "
    "furniture, surfaces, and surroundings visible in each historical frame. Use these visual "
    "clues to infer WHERE the object likely is, even if you cannot see it in the current view. "
    "Give a confident, specific answer like: 'I last saw your wallet on the wooden desk near "
    "a monitor, in what looked like a bedroom with blue walls. You appear to be in the kitchen "
    "right now - try heading back to your bedroom and check the desk.' If no historical images "
    "are provided but you remember seeing the object in conversation history, use that text "
    "context to guide the user. Always prioritize the most recent sighting."
)

# Patterns for extracting personal facts from user speech
PERSONAL_FACT_PATTERNS = [
    # Name
    (r"my name is (\w+)", "name"),
    (r"i'm (\w+)", "name"),
    (r"call me (\w+)", "name"),
    # Location / address
    (r"i live (?:at|in|on) (.+?)(?:\.|$)", "home_location"),
    (r"my address is (.+?)(?:\.|$)", "home_location"),
    # Occupation
    (r"i (?:work as|am) (?:a |an )?(.+?)(?:\.|$)", "occupation"),
    # Allergies / medical
    (r"i'm allergic to (.+?)(?:\.|$)", "allergy"),
    (r"i have (?:a )?(.+?) allergy", "allergy"),
    # Preferences
    (r"i prefer (.+?)(?:\.|$)", "preference"),
    (r"i like (.+?)(?:\.|$)", "preference"),
    # Explicit memory requests
    (r"remember (?:that |this: ?)(.+?)(?:\.|$)", "remembered_fact"),
    (r"don't forget (?:that )?(.+?)(?:\.|$)", "remembered_fact"),
]


class ConversationManager:
    """
    Manages rolling conversation history for multi-turn Gemini interactions.
    
    Features:
    - Session management with auto-timeout (5 min silence = new session)
    - Full session history (no turn limit, user's choice)
    - SQLite persistence for each turn (immediate write)
    - User profile with personal fact extraction
    - Context-aware response length limits
    - Dynamic system instruction composition
    """

    def __init__(
        self,
        db_path: str = "local_cortex.db",
        session_timeout: int = 300,
        max_turns: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize ConversationManager.
        
        Args:
            db_path: Path to SQLite database (shared with HybridMemoryManager)
            session_timeout: Seconds of silence before starting new session (default: 300)
            max_turns: Max turns to keep in memory (None = unlimited, user's choice)
            config: Conversation config dict from config.yaml
        """
        logger.info("Initializing ConversationManager...")
        
        self.db_path = db_path
        self.session_timeout = session_timeout
        self.max_turns = max_turns
        self.config = config or {}
        
        # Session state
        self.session_id: str = str(uuid4())
        self.session_start: float = time.time()
        self.last_activity: float = time.time()
        self.turns: List[Dict[str, Any]] = []  # {role, content, timestamp, query_type}
        
        # User profile (loaded from SQLite)
        self.user_profile: Dict[str, str] = {}
        
        # Response limits from config
        self.response_limits = self.config.get('response_limits', {
            'detection_full': 150,
            'detection_count': 100,
            'analysis_ocr': 0,
            'analysis_describe': 400,
            'analysis_safety': 300,
            'follow_up': 400,
            'default': 200,
        })
        
        # Agentic vision config
        self.agentic_config = self.config.get('agentic_vision', {})
        self.agentic_enabled = self.agentic_config.get('enabled', True)
        self.agentic_query_types = set(self.agentic_config.get('enabled_query_types', [
            'analysis_ocr', 'analysis_describe'
        ]))
        
        # Personalization config
        self.personalization_config = self.config.get('personalization', {})
        self.personalization_enabled = self.personalization_config.get('enabled', True)
        self.extract_facts_enabled = self.personalization_config.get('extract_facts', True)
        
        # Memory image storage directory
        self.memory_images_dir = Path(self.config.get('memory_images_dir', 'memory_images'))
        self.memory_images_dir.mkdir(parents=True, exist_ok=True)
        
        # Context compression threshold (chars, ~1MB = ~250K chars in UTF-8)
        self.compression_threshold = self.config.get('context_compression_threshold_chars', 250000)
        
        # Initialize SQLite tables
        self._init_db()
        
        # Load user profile from SQLite
        self.load_user_profile()
        
        # Try to restore last session if within timeout
        self._try_restore_session()
        
        logger.info(f"ConversationManager initialized (session: {self.session_id[:8]}...)")
        logger.info(f"  Session timeout: {self.session_timeout}s")
        logger.info(f"  Max turns: {'unlimited' if self.max_turns is None else self.max_turns}")
        logger.info(f"  User profile: {len(self.user_profile)} facts loaded")

    def _init_db(self):
        """Initialize SQLite tables for conversations and user profile."""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            
            # Conversations table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations_local (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    query_type TEXT,
                    timestamp REAL NOT NULL,
                    image_path TEXT,
                    full_response TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_session
                ON conversations_local(session_id, timestamp)
            """)
            
            # Migration: add image_path and full_response columns if missing
            # (for existing databases created before this update)
            try:
                conn.execute("ALTER TABLE conversations_local ADD COLUMN image_path TEXT")
                logger.info("Migrated: added image_path column")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE conversations_local ADD COLUMN full_response TEXT")
                logger.info("Migrated: added full_response column")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Full-text search index on full_response for object recall
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_content
                ON conversations_local(content)
            """)
            
            # User profile table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            
            conn.commit()
            conn.close()
            logger.info("Conversation tables initialized in SQLite")
        except Exception as e:
            logger.error(f"Failed to initialize conversation tables: {e}")

    def _get_db(self) -> sqlite3.Connection:
        """Get a SQLite connection (short-lived, for thread safety)."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _check_session_timeout(self):
        """Check if session has timed out and start a new one if needed."""
        elapsed = time.time() - self.last_activity
        if elapsed > self.session_timeout:
            logger.info(
                f"Session timeout ({elapsed:.0f}s > {self.session_timeout}s). "
                f"Starting new session."
            )
            self.save_session()
            self._start_new_session()

    def _start_new_session(self):
        """Start a fresh conversation session."""
        self.session_id = str(uuid4())
        self.session_start = time.time()
        self.last_activity = time.time()
        self.turns = []
        logger.info(f"New session started: {self.session_id[:8]}...")

    def save_image(self, pil_image) -> Optional[str]:
        """
        Save a camera frame as JPEG for visual memory.
        
        Args:
            pil_image: PIL Image object (camera frame)
            
        Returns:
            Saved file path relative to project root, or None on failure
        """
        try:
            # Create session subdirectory
            session_dir = self.memory_images_dir / self.session_id[:8]
            session_dir.mkdir(parents=True, exist_ok=True)
            
            # Save as JPEG with quality 80 (~50-100KB per frame)
            filename = f"{int(time.time() * 1000)}.jpg"
            filepath = session_dir / filename
            pil_image.save(str(filepath), "JPEG", quality=80)
            
            relative_path = str(filepath)
            logger.info(f"[MEMORY] Saved memory image: {relative_path} ({os.path.getsize(filepath)} bytes)")
            return relative_path
        except Exception as e:
            logger.error(f"Failed to save memory image: {e}")
            return None

    def add_turn(
        self,
        role: str,
        content: str,
        query_type: Optional[str] = None,
        image_path: Optional[str] = None,
        full_response: Optional[str] = None,
    ):
        """
        Add a conversation turn (user or model).
        
        Persists immediately to SQLite for crash recovery.
        Auto-starts new session if timeout exceeded.
        
        Args:
            role: "user" or "model"
            content: The spoken/truncated text content of the turn
            query_type: Optional query type (e.g., "analysis_ocr")
            image_path: Optional path to saved camera frame JPEG
            full_response: Optional full untruncated Gemini response (model turns only)
        """
        # Check for session timeout before adding
        self._check_session_timeout()
        
        now = time.time()
        self.last_activity = now
        
        turn = {
            "role": role,
            "content": content,
            "timestamp": now,
            "query_type": query_type,
            "image_path": image_path,
            "full_response": full_response,
        }
        self.turns.append(turn)
        
        # Persist to SQLite immediately
        try:
            conn = self._get_db()
            conn.execute(
                """INSERT INTO conversations_local 
                   (session_id, role, content, query_type, timestamp, image_path, full_response)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.session_id, role, content, query_type, now, image_path, full_response)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to persist conversation turn: {e}")
        
        # Trim if max_turns is set
        if self.max_turns is not None and len(self.turns) > self.max_turns * 2:
            # Keep last max_turns pairs (user + model)
            self.turns = self.turns[-(self.max_turns * 2):]
        
        logger.info(
            f"[MEMORY] Turn added: {role} ({len(content)} chars), "
            f"session has {len(self.turns)} turns"
            f"{', image=' + image_path if image_path else ''}"
        )

    def get_history_for_gemini(self) -> List[Dict[str, Any]]:
        """
        Build multi-turn contents list for Gemini API.
        
        Uses full_response (untruncated) for model turns when available,
        giving Gemini richer context about past observations. If total
        context exceeds the compression threshold (~1MB / 250K chars),
        older turns are summarized into a condensed "Previously observed:" block
        while recent turns are kept verbatim.
        
        The current turn's image is added by the caller.
        
        Returns:
            List of {"role": "user"|"model", "content": str}
        """
        if not self.turns:
            logger.info("[MEMORY] get_history_for_gemini: 0 turns available")
            return []
        
        # Build raw history using full_response when available
        raw_history = []
        for turn in self.turns:
            content = turn["content"]
            # Use full untruncated response for model turns (richer context)
            if turn["role"] == "model" and turn.get("full_response"):
                content = turn["full_response"]
            raw_history.append({
                "role": turn["role"],
                "content": content,
            })
        
        # Check total context size
        total_chars = sum(len(h["content"]) for h in raw_history)
        
        if total_chars <= self.compression_threshold:
            # Under threshold — return full history as-is
            logger.info(f"[MEMORY] get_history_for_gemini: {len(raw_history)} turns, {total_chars} chars (no compression)")
            return raw_history
        
        # Over threshold — compress older turns, keep recent 20 verbatim
        logger.info(
            f"Context compression: {total_chars} chars > {self.compression_threshold} threshold. "
            f"Compressing older turns."
        )
        
        keep_recent = 20  # Keep last 20 turns verbatim (10 exchanges)
        recent = raw_history[-keep_recent:] if len(raw_history) > keep_recent else raw_history
        older = raw_history[:-keep_recent] if len(raw_history) > keep_recent else []
        
        if not older:
            return recent
        
        # Summarize older turns into condensed bullet points
        # Extract key observations from model responses
        summary_parts = []
        for turn in older:
            if turn["role"] == "model":
                # Take first 200 chars of each old model response as summary
                text = turn["content"][:200].strip()
                if text:
                    summary_parts.append(f"- {text}")
        
        if summary_parts:
            summary_text = (
                "Summary of earlier observations:\n"
                + "\n".join(summary_parts[:30])  # Cap at 30 bullet points
            )
            compressed = [{"role": "user", "content": summary_text}]
            compressed.extend(recent)
            
            new_total = sum(len(h["content"]) for h in compressed)
            logger.info(f"Compressed context: {total_chars} -> {new_total} chars")
            return compressed
        
        return recent

    def build_system_instruction(self) -> str:
        """
        Compose dynamic system instruction from user profile + defaults.
        
        Includes personalization if enabled and profile has data.
        
        Returns:
            System instruction string for Gemini
        """
        if not self.personalization_enabled or not self.user_profile:
            return self.personalization_config.get(
                'default_system_instruction', DEFAULT_SYSTEM_INSTRUCTION
            )
        
        # Start with default instruction
        instruction = self.personalization_config.get(
            'default_system_instruction', DEFAULT_SYSTEM_INSTRUCTION
        )
        
        # Add personalization context
        personal_parts = []
        
        name = self.user_profile.get('name')
        if name:
            personal_parts.append(f"The user's name is {name}.")
        
        occupation = self.user_profile.get('occupation')
        if occupation:
            personal_parts.append(f"They work as {occupation}.")
        
        home = self.user_profile.get('home_location')
        if home:
            personal_parts.append(f"They live at {home}.")
        
        # Add allergies (safety-critical)
        allergy = self.user_profile.get('allergy')
        if allergy:
            personal_parts.append(
                f"IMPORTANT: The user is allergic to {allergy}. "
                "Always warn if detected in food labels or environments."
            )
        
        # Add preferences
        preference = self.user_profile.get('preference')
        if preference:
            personal_parts.append(f"User preference: {preference}.")
        
        # Add remembered facts
        remembered = self.user_profile.get('remembered_fact')
        if remembered:
            personal_parts.append(f"User asked to remember: {remembered}.")
        
        if personal_parts:
            instruction += "\n\nPersonal context:\n" + "\n".join(personal_parts)
        
        return instruction

    def extract_personal_facts(self, text: str):
        """
        Extract personal facts from user speech using regex patterns.
        
        Triggered keywords: "my name is", "I live at", "remember that", etc.
        Stores extracted facts to SQLite user_profile table.
        
        Args:
            text: User's speech text
        """
        if not self.extract_facts_enabled:
            return
        
        text_lower = text.lower().strip()
        
        for pattern, fact_key in PERSONAL_FACT_PATTERNS:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if len(value) < 2 or len(value) > 200:
                    continue  # Skip too short or too long
                
                # Capitalize names
                if fact_key == "name":
                    value = value.capitalize()
                
                logger.info(f"Personal fact extracted: {fact_key} = '{value}'")
                self.store_user_profile(fact_key, value)

    def get_response_limit(self, query_type: str) -> int:
        """
        Get character limit for response based on query type and context.
        
        If the conversation has prior turns (follow-up), uses the follow_up limit.
        Returns 0 for no cap (e.g., OCR reads).
        
        Args:
            query_type: Router's query_type string
            
        Returns:
            Character limit (0 = no limit)
        """
        # Follow-up detection: if there's prior conversation context, allow longer responses
        if len(self.turns) >= 2:  # At least one prior exchange
            # Use follow_up limit unless the specific type has a higher or zero limit
            follow_up_limit = self.response_limits.get('follow_up', 400)
            type_limit = self.response_limits.get(query_type, self.response_limits.get('default', 200))
            
            # Zero means no cap (OCR) -- always honor that
            if type_limit == 0:
                return 0
            
            return max(follow_up_limit, type_limit)
        
        # First query in session -- use type-specific limit
        limit = self.response_limits.get(query_type, self.response_limits.get('default', 200))
        return limit

    def should_enable_code_execution(self, query_type: str) -> bool:
        """
        Determine if agentic vision (code execution) should be enabled.
        
        Args:
            query_type: Router's query_type string
            
        Returns:
            True if code execution should be enabled for this query
        """
        if not self.agentic_enabled:
            return False
        return query_type in self.agentic_query_types

    def save_session(self):
        """
        Flush current session state. Called on shutdown or session timeout.
        
        Turns are already persisted individually in add_turn(), so this
        is mainly for logging and any cleanup.
        """
        if self.turns:
            logger.info(
                f"Session {self.session_id[:8]}... saved: "
                f"{len(self.turns)} turns, "
                f"duration {time.time() - self.session_start:.0f}s"
            )

    def _try_restore_session(self):
        """
        On startup, always restore the last session regardless of age.
        
        Sessions persist indefinitely across restarts. A new session is only
        started during runtime if the user is silent for session_timeout seconds.
        """
        try:
            conn = self._get_db()
            cursor = conn.execute("""
                SELECT session_id, MAX(timestamp) as last_ts
                FROM conversations_local
                GROUP BY session_id
                ORDER BY last_ts DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            
            if row:
                last_session_id = row['session_id']
                last_timestamp = row['last_ts']
                age = time.time() - last_timestamp
                
                # Always restore — sessions persist indefinitely
                self.session_id = last_session_id
                self.session_start = last_timestamp  # Approximate
                self.last_activity = time.time()  # Reset activity to NOW so timeout starts fresh
                
                # Load turns (including image_path and full_response)
                turns_cursor = conn.execute("""
                    SELECT role, content, query_type, timestamp, image_path, full_response
                    FROM conversations_local
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                """, (last_session_id,))
                
                for turn_row in turns_cursor:
                    self.turns.append({
                        "role": turn_row['role'],
                        "content": turn_row['content'],
                        "query_type": turn_row['query_type'],
                        "timestamp": turn_row['timestamp'],
                        "image_path": turn_row['image_path'],
                        "full_response": turn_row['full_response'],
                    })
                
                logger.info(
                    f"Restored session {last_session_id[:8]}... "
                    f"({len(self.turns)} turns, {age:.0f}s old)"
                )
            
            conn.close()
        except Exception as e:
            logger.warning(f"Could not restore session: {e}")

    def load_user_profile(self):
        """Load user profile from SQLite."""
        try:
            conn = self._get_db()
            cursor = conn.execute("SELECT key, value FROM user_profile")
            self.user_profile = {}
            for row in cursor:
                self.user_profile[row['key']] = row['value']
            conn.close()
            
            if self.user_profile:
                logger.info(f"User profile loaded: {list(self.user_profile.keys())}")
        except Exception as e:
            logger.warning(f"Could not load user profile: {e}")

    def store_user_profile(self, key: str, value: str):
        """
        Store a user profile fact to SQLite (upsert).
        
        Args:
            key: Profile key (e.g., 'name', 'allergy')
            value: Profile value
        """
        try:
            conn = self._get_db()
            conn.execute(
                """INSERT INTO user_profile (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
                (key, value, time.time(), value, time.time())
            )
            conn.commit()
            conn.close()
            
            # Update in-memory cache
            self.user_profile[key] = value
            logger.info(f"User profile updated: {key} = '{value}'")
        except Exception as e:
            logger.error(f"Failed to store user profile: {e}")

    def cleanup_old_conversations(self, days: int = 7):
        """
        Delete conversations older than N days from SQLite.
        
        Args:
            days: Delete conversations older than this many days
        """
        cutoff = time.time() - (days * 86400)
        try:
            conn = self._get_db()
            cursor = conn.execute(
                "DELETE FROM conversations_local WHERE timestamp < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            if deleted > 0:
                logger.info(f"Cleaned up {deleted} conversation turns older than {days} days")
        except Exception as e:
            logger.error(f"Failed to cleanup old conversations: {e}")

    # =================================================================
    # Object Recall — Search & Spatial Memory
    # =================================================================

    def extract_search_object(self, query: str) -> Optional[str]:
        """
        Extract the target object name from spatial/search queries.
        
        Examples:
            'where is my wallet?' -> 'wallet'
            'find my mechanical keyboard' -> 'mechanical keyboard'
            'have you seen my red bag?' -> 'red bag'
            'locate the water bottle' -> 'water bottle'
        
        Args:
            query: User's voice query
            
        Returns:
            Object name string, or None if query isn't a search query
        """
        query_lower = query.lower().strip().rstrip('?').rstrip('.')
        
        # Patterns to extract the target object
        search_patterns = [
            r"where (?:is|are) (?:my |the )?(.+)",
            r"find (?:my |the )?(.+)",
            r"locate (?:my |the )?(.+)",
            r"have you seen (?:my |the )?(.+)",
            r"can you (?:see|find|spot) (?:my |the )?(.+)",
            r"do you (?:see|know where) (?:my |the )?(.+?) (?:is|are)",
            r"i(?:'m| am) looking for (?:my |the |a )?(.+)",
            r"help me find (?:my |the |a )?(.+)",
            r"where did i (?:put|leave|place) (?:my |the )?(.+)",
        ]
        
        for pattern in search_patterns:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                obj = match.group(1).strip()
                # Clean up common trailing words
                obj = re.sub(r'\s+(right now|please|again|at|is)$', '', obj)
                if 2 <= len(obj) <= 50:
                    logger.info(f"Object recall: extracted '{obj}' from query")
                    return obj
        
        return None

    def search_object_in_history(self, object_name: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Search conversation history for mentions of an object.
        
        Searches both the spoken content and the full untruncated response
        stored in memory. Returns matching turns with their image paths.
        
        Args:
            object_name: Object to search for (e.g., 'wallet', 'keyboard')
            limit: Max number of matches to return (default 3, most recent first)
            
        Returns:
            List of dicts with keys: content, full_response, image_path, timestamp, session_id
        """
        results = []
        search_term = f"%{object_name}%"
        
        try:
            conn = self._get_db()
            cursor = conn.execute("""
                SELECT session_id, role, content, full_response, image_path, timestamp
                FROM conversations_local
                WHERE (content LIKE ? OR full_response LIKE ?)
                  AND role = 'model'
                ORDER BY timestamp DESC
                LIMIT ?
            """, (search_term, search_term, limit))
            
            for row in cursor:
                results.append({
                    "session_id": row['session_id'],
                    "content": row['content'],
                    "full_response": row['full_response'],
                    "image_path": row['image_path'],
                    "timestamp": row['timestamp'],
                })
            
            conn.close()
            
            if results:
                logger.info(
                    f"Object recall: found {len(results)} mentions of '{object_name}' "
                    f"in conversation history"
                )
            else:
                logger.info(f"Object recall: no mentions of '{object_name}' found")
                
        except Exception as e:
            logger.error(f"Object recall search failed: {e}")
        
        return results

    def get_session_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the current session for diagnostics.
        
        Returns:
            Dict with session stats
        """
        return {
            "session_id": self.session_id[:8],
            "turns": len(self.turns),
            "duration_s": time.time() - self.session_start,
            "last_activity_s_ago": time.time() - self.last_activity,
            "user_profile_facts": len(self.user_profile),
            "personalization_enabled": self.personalization_enabled,
            "agentic_vision_enabled": self.agentic_enabled,
        }
