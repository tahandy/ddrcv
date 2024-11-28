import cv2
import threading
import time
import logging
from queue import Queue, Empty


class VideoFrameFetcher:
    def __init__(self, source, queue_size=1, reconnect_delay=5, hw_accel=False, logger=None):
        """
        Initialize the video frame fetcher.

        :param source: The video source. Can be an RTSP URL or a device path (e.g., `/dev/video0` or an integer for webcams).
        :param queue_size: Maximum number of frames to store in the queue.
        :param reconnect_delay: Delay before attempting reconnection (for RTSP streams only).
        :param hw_accel: Use hardware acceleration if available (for RTSP streams).
        """
        if logger is None:
            self.logger = logging.getLogger('VideoFrameFetcher')
        else:
            self.logger = logger

        if source is None or source == '':
            self.logger.error('[VideoFrameFetcher] Source must not be None or empty')
            raise ValueError('[VideoFrameFetcher] Source must not be None or empty')

        self.source = source
        self.frame_queue = Queue(maxsize=queue_size)
        self.capture = None
        self.thread = None
        self.running = False
        self.reconnect_delay = reconnect_delay
        self.hw_accel = hw_accel

    def start(self):
        """
        Start the frame fetching thread.
        """
        self.running = True
        self.thread = threading.Thread(target=self.update_frame, daemon=True)
        self.thread.start()
        self.logger.info("Frame fetching thread started.")

    def update_frame(self):
        """
        Continuously fetch frames from the video source.
        """
        while self.running:
            if self.capture is None or not self.capture.isOpened():
                self.logger.info("Attempting to connect to the video source.")
                self.connect()
                if not self.capture or not self.capture.isOpened():
                    self.logger.warning(
                        f"Connection failed. Retrying in {self.reconnect_delay} seconds."
                    )
                    time.sleep(self.reconnect_delay)
                    continue
                else:
                    self.logger.info("Successfully connected to the video source.")

            ret, frame = self.capture.read()
            if not ret or frame is None:
                self.logger.error("Failed to read frame from the source.")
                # Stream/device might have dropped, attempt reconnection
                self.capture.release()
                self.capture = None
                self.logger.info(
                    f"Reconnecting to the source in {self.reconnect_delay} seconds."
                )
                time.sleep(self.reconnect_delay)
                continue

            # Clear the queue to keep only the latest frame
            while not self.frame_queue.empty():
                try:
                    discarded_frame = self.frame_queue.get_nowait()
                    del discarded_frame  # Free memory
                except Empty:
                    break

            self.frame_queue.put(frame)
            self.logger.debug("New frame fetched and added to the queue.")

    def connect(self):
        """
        Establish connection to the video source.
        """
        try:
            if isinstance(self.source, str) and self.source.startswith('rtsp://'):
                # RTSP source
                if self.hw_accel:
                    self.logger.info("Attempting hardware acceleration for RTSP stream.")
                    gst_str_hw = (
                        f'rtspsrc location={self.source} protocols=tcp latency=0 ! '
                        'rtph264depay ! h264parse ! nvh264dec ! '
                        'videoconvert ! appsink sync=false'
                    )
                    self.capture = cv2.VideoCapture(gst_str_hw, cv2.CAP_GSTREAMER)
                else:
                    self.logger.info("Attempting software decoding for RTSP stream.")
                    self.capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
            else:
                # Video device
                self.logger.info(f"Connecting to video device {self.source}.")
                self.capture = cv2.VideoCapture(self.source)

            if not self.capture.isOpened():
                self.logger.error("Failed to open video source.")
                self.capture = None
        except Exception as e:
            self.logger.exception(f"Exception occurred while connecting: {e}")
            self.capture = None

    def get_frame(self):
        """
        Retrieve the most recent frame.

        :return: The latest frame if available, else None.
        """
        try:
            frame = self.frame_queue.get_nowait()
            self.logger.debug("Frame retrieved from the queue.")
            return frame
        except Empty:
            self.logger.debug("No frame available in the queue.")
            return None

    def stop(self):
        """
        Stop the frame fetching thread and release resources.
        """
        self.running = False
        if self.thread is not None:
            self.thread.join()
            self.thread = None
            self.logger.info("Frame fetching thread stopped.")
        if self.capture is not None:
            self.capture.release()
            self.capture = None
            self.logger.info("Video capture released.")

    def __del__(self):
        self.stop()


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # Replace with your video source (e.g., '/dev/video0' for a video device)
    video_source = '/dev/video0'

    # Initialize and start the frame fetcher
    fetcher = VideoFrameFetcher(video_source)
    fetcher.start()

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                # Display the frame (optional)
                cv2.imshow('Video Stream', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                # Wait until a frame is available
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up
        fetcher.stop()
        cv2.destroyAllWindows()
        fetcher.logger.info("Application terminated.")
