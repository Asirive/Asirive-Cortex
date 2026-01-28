"""
Vision Query Handler - "What do you see?" Pipeline
===================================================

Handles Layer 1 detection queries by combining:
- Layer 0: YOLO NCNN on RPi5 (local, fast)
- Layer 1: YOLOE on Laptop via WebSocket (more accurate, GPU)

Aggregates detections and generates TTS response.

Author: Haziq (@IRSPlays)
Project: Cortex v2.0 - YIA 2026
Date: January 27, 2026
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class VisionQueryHandler:
    """
    Handles "what do you see" and similar detection queries.
    
    Workflow:
    1. Capture current frame from camera
    2. Run Layer 0 (YOLO NCNN) locally on RPi5
    3. Request Layer 1 (YOLOE) from laptop via WebSocket
    4. Merge and aggregate detections
    5. Generate TTS response
    """
    
    def __init__(
        self,
        layer0_detector=None,
        websocket_client=None,
        camera_capture: Optional[Callable] = None,
        layer1_timeout: float = 2.0
    ):
        """
        Initialize Vision Query Handler.
        
        Args:
            layer0_detector: YOLO NCNN detector instance (Layer 0)
            websocket_client: FastAPI WebSocket client for laptop communication
            camera_capture: Function to capture current frame, returns numpy array
            layer1_timeout: Timeout for Layer 1 response from laptop (seconds)
        """
        self.layer0_detector = layer0_detector
        self.websocket_client = websocket_client
        self.camera_capture = camera_capture
        self.layer1_timeout = layer1_timeout
        
        # Import aggregator
        try:
            from rpi5.layer3_guide.detection_aggregator import DetectionAggregator
            self.aggregator = DetectionAggregator(min_confidence=0.25)
        except ImportError:
            logger.error("Failed to import DetectionAggregator")
            self.aggregator = None
        
        # Import TTS router
        try:
            from rpi5.tts_router import TTSRouter
            self.tts_router = TTSRouter()
        except ImportError:
            logger.error("Failed to import TTSRouter")
            self.tts_router = None
        
        # Pending Layer 1 responses
        self._layer1_response: Optional[List[Dict]] = None
        self._layer1_event = asyncio.Event()
        
        logger.info("VisionQueryHandler initialized")
    
    def set_layer0_detector(self, detector):
        """Set the Layer 0 detector after initialization."""
        self.layer0_detector = detector
    
    def set_websocket_client(self, client):
        """Set the WebSocket client after initialization."""
        self.websocket_client = client
    
    def set_camera_capture(self, capture_func: Callable):
        """Set the camera capture function."""
        self.camera_capture = capture_func
    
    async def handle_query(
        self,
        query: str,
        frame=None,
        speak_result: bool = True
    ) -> Dict[str, Any]:
        """
        Handle a vision detection query.
        
        Args:
            query: User's voice query (e.g., "what do you see")
            frame: Optional pre-captured frame (captures new if None)
            speak_result: If True, speak the result via TTS
            
        Returns:
            Dict with:
                - success: True if detection completed
                - text: Human-readable result
                - layer0_detections: List of Layer 0 detections
                - layer1_detections: List of Layer 1 detections
                - merged: Aggregated detection info
                - latency_ms: Total processing time
        """
        start_time = time.perf_counter()
        
        result = {
            "success": False,
            "text": "",
            "query": query,
            "layer0_detections": [],
            "layer1_detections": [],
            "merged": None,
            "latency_ms": 0
        }
        
        try:
            # Step 1: Capture frame if not provided
            if frame is None and self.camera_capture:
                frame = self.camera_capture()
                if frame is None:
                    result["text"] = "I couldn't capture an image from the camera."
                    return result
            
            if frame is None:
                result["text"] = "No camera available."
                return result
            
            # Step 2: Run Layer 0 and Layer 1 in parallel
            layer0_task = asyncio.create_task(self._run_layer0(frame))
            layer1_task = asyncio.create_task(self._request_layer1(frame))
            
            # Wait for both with timeout for Layer 1
            layer0_detections = await layer0_task
            
            try:
                layer1_detections = await asyncio.wait_for(
                    layer1_task,
                    timeout=self.layer1_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Layer 1 timeout after {self.layer1_timeout}s, using Layer 0 only")
                layer1_detections = []
            
            result["layer0_detections"] = layer0_detections
            result["layer1_detections"] = layer1_detections
            
            # Step 3: Aggregate detections
            if self.aggregator:
                if layer1_detections:
                    merged = self.aggregator.merge_layers(layer0_detections, layer1_detections)
                else:
                    merged = self.aggregator.aggregate(layer0_detections, "layer0")
                
                result["merged"] = merged
                result["text"] = self.aggregator.format_for_speech(merged)
            else:
                # Fallback if aggregator not available
                total = len(layer0_detections) + len(layer1_detections)
                result["text"] = f"I detected {total} objects."
            
            result["success"] = True
            
            # Step 4: Speak result via TTS
            if speak_result and self.tts_router:
                await self.tts_router.speak_async(result["text"])
            
        except Exception as e:
            logger.error(f"Vision query error: {e}", exc_info=True)
            result["text"] = "I encountered an error while processing your request."
        
        result["latency_ms"] = (time.perf_counter() - start_time) * 1000
        logger.info(f"Vision query completed in {result['latency_ms']:.0f}ms: {result['text']}")
        
        return result
    
    async def _run_layer0(self, frame) -> List[Dict[str, Any]]:
        """
        Run Layer 0 YOLO NCNN detection on RPi5.
        
        Args:
            frame: numpy array (BGR image)
            
        Returns:
            List of detection dicts
        """
        if not self.layer0_detector:
            logger.warning("Layer 0 detector not available")
            return []
        
        try:
            # Run detection (this should be the YOLO NCNN detector)
            # Expected method: detect(frame) -> list of detections
            detections = await asyncio.to_thread(
                self._run_layer0_sync, frame
            )
            
            logger.debug(f"Layer 0: {len(detections)} detections")
            return detections
            
        except Exception as e:
            logger.error(f"Layer 0 detection error: {e}")
            return []
    
    def _run_layer0_sync(self, frame) -> List[Dict[str, Any]]:
        """Synchronous Layer 0 detection."""
        try:
            # Handle different detector interfaces
            if hasattr(self.layer0_detector, 'detect'):
                results = self.layer0_detector.detect(frame)
            elif hasattr(self.layer0_detector, 'run'):
                results = self.layer0_detector.run(frame)
            elif hasattr(self.layer0_detector, '__call__'):
                results = self.layer0_detector(frame)
            else:
                logger.error("Layer 0 detector has no detect/run method")
                return []
            
            # Normalize results to standard format
            detections = []
            for r in results if results else []:
                detection = {
                    "class_name": r.get("class_name", r.get("class", r.get("name", "unknown"))),
                    "confidence": r.get("confidence", r.get("conf", 0.5)),
                    "bbox": r.get("bbox", r.get("box", [])),
                    "source": "layer0"
                }
                detections.append(detection)
            
            return detections
            
        except Exception as e:
            logger.error(f"Layer 0 sync detection error: {e}")
            return []
    
    async def _request_layer1(self, frame) -> List[Dict[str, Any]]:
        """
        Request Layer 1 detection from laptop via WebSocket.
        
        Args:
            frame: numpy array (BGR image)
            
        Returns:
            List of detection dicts from laptop
        """
        if not self.websocket_client:
            logger.debug("WebSocket client not available, skipping Layer 1")
            return []
        
        try:
            # Reset response
            self._layer1_response = None
            self._layer1_event.clear()
            
            # Send frame to laptop for Layer 1 inference
            # The websocket client should handle encoding and sending
            if hasattr(self.websocket_client, 'request_layer1_inference'):
                await self.websocket_client.request_layer1_inference(frame)
            elif hasattr(self.websocket_client, 'send_frame_for_inference'):
                await self.websocket_client.send_frame_for_inference(frame)
            else:
                # Try generic send with message type
                import cv2
                import base64
                
                # Encode frame as JPEG
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                frame_b64 = base64.b64encode(buffer).decode('utf-8')
                
                message = {
                    "type": "LAYER1_QUERY",
                    "action": "detect",
                    "frame": frame_b64
                }
                
                if hasattr(self.websocket_client, 'send_json'):
                    await self.websocket_client.send_json(message)
                elif hasattr(self.websocket_client, 'send'):
                    import json
                    await self.websocket_client.send(json.dumps(message))
                else:
                    logger.error("WebSocket client has no send method")
                    return []
            
            # Wait for response (with timeout handled by caller)
            await self._layer1_event.wait()
            
            return self._layer1_response or []
            
        except Exception as e:
            logger.error(f"Layer 1 request error: {e}")
            return []
    
    def on_layer1_response(self, detections: List[Dict[str, Any]]):
        """
        Callback when Layer 1 response is received from laptop.
        
        Args:
            detections: List of detection dicts from laptop
        """
        self._layer1_response = detections
        self._layer1_event.set()
        logger.debug(f"Received Layer 1 response: {len(detections)} detections")
    
    async def handle_query_simple(
        self,
        query: str,
        layer0_detections: List[Dict[str, Any]],
        layer1_detections: Optional[List[Dict[str, Any]]] = None,
        speak_result: bool = True
    ) -> str:
        """
        Simplified query handler when detections are already available.
        
        Use this when detection is running continuously and you just need
        to aggregate and speak the current results.
        
        Args:
            query: User's voice query
            layer0_detections: Current Layer 0 detections
            layer1_detections: Optional Layer 1 detections from laptop
            speak_result: If True, speak via TTS
            
        Returns:
            Human-readable result string
        """
        try:
            if self.aggregator:
                if layer1_detections:
                    merged = self.aggregator.merge_layers(layer0_detections, layer1_detections)
                else:
                    merged = self.aggregator.aggregate(layer0_detections, "layer0")
                
                text = self.aggregator.format_for_speech(merged)
            else:
                total = len(layer0_detections) + len(layer1_detections or [])
                text = f"I see {total} objects."
            
            if speak_result and self.tts_router:
                await self.tts_router.speak_async(text)
            
            return text
            
        except Exception as e:
            logger.error(f"Simple query error: {e}")
            return "I encountered an error."


# =============================================================================
# Singleton access
# =============================================================================

_handler_instance: Optional[VisionQueryHandler] = None


def get_vision_handler() -> VisionQueryHandler:
    """Get singleton VisionQueryHandler instance."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = VisionQueryHandler()
    return _handler_instance


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Test with mock data
    handler = VisionQueryHandler()
    
    # Mock detections
    layer0 = [
        {"class_name": "person", "confidence": 0.92, "bbox": [100, 100, 200, 300]},
        {"class_name": "chair", "confidence": 0.85, "bbox": [300, 200, 400, 400]},
    ]
    
    layer1 = [
        {"class_name": "storage box", "confidence": 0.78, "bbox": [50, 50, 150, 150]},
        {"class_name": "storage box", "confidence": 0.82, "bbox": [200, 50, 300, 150]},
        {"class_name": "laptop", "confidence": 0.91, "bbox": [400, 100, 550, 200]},
    ]
    
    async def test():
        result = await handler.handle_query_simple(
            "what do you see",
            layer0,
            layer1,
            speak_result=False  # Don't actually speak in test
        )
        print(f"Result: {result}")
    
    asyncio.run(test())
