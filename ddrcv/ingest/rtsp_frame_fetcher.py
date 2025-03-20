import cv2
import threading
import time
import logging
from queue import Queue, Empty


class RTSPFrameFetcher:
    def __init__(self, rtsp_url, queue_size=1, reconnect_delay=5, hw_accel=True, logger=None):
        """
        Initialize the RTSP frame fetcher.

        :param rtsp_url: The RTSP stream URL.
        :param queue_size: Maximum number of frames to store in the queue.
        :param reconnect_delay: Delay before attempting reconnection (in seconds).
        :param hw_accel: Use hardware acceleration if available.
        """
        if logger is None:
            self.logger = logging.getLogger('RTSPFrameFetcher')
        else:
            self.logger = logger

        if rtsp_url is None or rtsp_url == '':
            self.logger.error('[RTSPFrameFetcher] RTSP URL must not be None or empty')
            raise ValueError('[RTSPFrameFetcher] RTSP URL must not be None or empty')

        self.rtsp_url = rtsp_url
        self.frame_queue = Queue(maxsize=queue_size)
        self.capture = None
        self.thread = None
        self.running = False
        self.reconnect_delay = reconnect_delay
        self.hw_accel = hw_accel

    @classmethod
    def from_config(cls, config, logger=None):
        url = config.pop('rtsp_url', None)
        if logger is None:
            logger = logging.getLogger('RTSPFrameFetcher')
        return RTSPFrameFetcher(url, logger=logger, **config)

    def start(self):
        """
        Start the frame fetching thread.
        """
        self.running = True
        self.thread = threading.Thread(target=self.update_frame, daemon=True)
        self.thread.start()
        self.logger.info("Frame fetching thread started.")
        print("Frame fetching thread started.")

    def update_frame(self):
        """
        Continuously fetch frames from the RTSP stream.
        """
        while self.running:
            if self.capture is None or not self.capture.isOpened():
                self.logger.info("Attempting to connect to the RTSP stream.")
                self.connect()
                if not self.capture or not self.capture.isOpened():
                    self.logger.warning(
                        f"Connection failed. Retrying in {self.reconnect_delay} seconds."
                    )
                    time.sleep(self.reconnect_delay)
                    continue
                else:
                    self.logger.info("Successfully connected to the RTSP stream.")
                    print("Successfully connected to the RTSP stream.")

            ret, frame = self.capture.read()
            if not ret or frame is None:
                self.logger.error("Failed to read frame from the stream.")
                # Stream might have dropped, attempt reconnection
                self.capture.release()
                self.capture = None
                self.logger.info(
                    f"Reconnecting to the stream in {self.reconnect_delay} seconds."
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
        Establish connection to the RTSP stream with optional hardware acceleration.
        """
        try:
            if self.hw_accel:
                # Try to use hardware acceleration via GStreamer
                self.logger.info("Attempting to use hardware acceleration for decoding via GStreamer.")
                gst_str_hw = (
                    f'rtspsrc location={self.rtsp_url} protocols=tcp latency=0 ! '
                    'rtph264depay ! h264parse ! nvh264dec ! '
                    'videoconvert ! appsink sync=false'
                )
                self.capture = cv2.VideoCapture(gst_str_hw, cv2.CAP_GSTREAMER)
                if self.capture.isOpened():
                    self.logger.info("Successfully connected using hardware acceleration via GStreamer.")
                    return
                else:
                    self.logger.warning("Hardware acceleration via GStreamer failed, attempting software decoding.")
                    pass

            # Attempt software decoding via FFMPEG
            self.logger.info("Attempting to use software decoding via FFMPEG.")
            self.capture = cv2.VideoCapture(str(self.rtsp_url), cv2.CAP_FFMPEG)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if self.capture.isOpened():
                self.logger.info("Successfully connected using software decoding via FFMPEG.")
                return
            else:
                self.logger.warning("Software decoding via FFMPEG failed, attempting software decoding via GStreamer.")
                print("Software decoding via FFMPEG failed, attempting software decoding via GStreamer.")

            # Attempt software decoding via GStreamer
            self.logger.info("Attempting to use software decoding via GStreamer.")
            gst_str_sw = (
                f'rtspsrc location={self.rtsp_url} protocols=tcp latency=0 ! '
                'rtph264depay ! h264parse ! avdec_h264 ! '
                'videoconvert ! appsink sync=false'
            )
            self.capture = cv2.VideoCapture(gst_str_sw, cv2.CAP_GSTREAMER)
            if self.capture.isOpened():
                self.logger.info("Successfully connected using software decoding via GStreamer.")
                pass
            else:
                self.logger.error("Failed to open video capture with software decoding via GStreamer.")
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

    # """
    # 'C:\Program Files\VideoLAN\VLC\vlc.exe' -vvv '.\videos\video.mp4' --rtsp-tcp --sout '#rtp{sdp=rtsp://:8554/stream}'
    # """

    # Replace with your RTSP stream URL
    rtsp_url = 'rtsp://localhost:8554/mystream'

    # Initialize and start the frame fetcher
    fetcher = RTSPFrameFetcher(rtsp_url, hw_accel=False)
    fetcher.start()

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                # Display the frame (optional)
                cv2.imshow('RTSP Stream', frame)
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
