import cv2
import threading
import time
import logging
from queue import Queue, Empty


class SimpleFrameFetcher:
    def __init__(self, device_idx: int, queue_size=1, reconnect_delay=5, logger=None, width=1920, height=1080, query_delay=0):
        """
        Initialize a simple CAP_ANY frame fetcher.

        :param device_idx: The source device index (run python -m cv2_enumerate_cameras to see a list,
                           likely want the OBS Virtual Camera if you're using this class)
        :param queue_size: Maximum number of frames to store in the queue.
        :param reconnect_delay: Delay before attempting reconnection (in seconds).
        """
        if logger is None:
            self.logger = logging.getLogger('SimpleFrameFetcher')
        else:
            self.logger = logger

        self.device_idx = device_idx
        self.frame_queue = Queue(maxsize=queue_size)
        self.capture = None
        self.thread = None
        self.running = False
        self.reconnect_delay = reconnect_delay
        self.width = width
        self.height = height
        self.query_delay = query_delay

    @classmethod
    def from_config(cls, config, logger=None):
        uri = config.pop('uri', None)
        if logger is None:
            logger = logging.getLogger('SimpleFrameFetcher')
        return SimpleFrameFetcher(uri, logger=logger, **config)

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
                self.logger.info(f"Attempting to connect to device {self.device_idx}.")
                self.connect()
                if not self.capture or not self.capture.isOpened():
                    self.logger.warning(
                        f"Connection failed. Retrying in {self.reconnect_delay} seconds."
                    )
                    time.sleep(self.reconnect_delay)
                    continue
                else:
                    self.logger.info("Successfully connected to the device stream.")
                    print("Successfully connected to the device stream.")

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
            if self.query_delay > 0:
                time.sleep(self.query_delay)


    def connect(self):
        try:
            self.logger.info("Attempting to use CAP_ANY.")
            self.capture = cv2.VideoCapture(self.device_idx, cv2.CAP_ANY)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if self.width is not None:
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)  # Set width to 1280 pixels
            if self.height is not None:
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height) # Set height to 720 pixels

            if self.capture.isOpened():
                self.logger.info("Successfully connected using CAP_ANY.")
                return
            else:
                self.logger.warning(f"Failed to connect to device with index {device_idx}")
                print(f"Failed to connect to device with index {device_idx}")

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
    device_idx = 1

    # Initialize and start the frame fetcher
    fetcher = SimpleFrameFetcher(device_idx, width=1920, height=1080)
    fetcher.start()

    try:
        while True:
            frame = fetcher.get_frame()
            if frame is not None:
                # Display the frame (optional)
                # cv2.imshow('RTSP Stream', frame)
                # if cv2.waitKey(1) & 0xFF == ord('q'):
                #     break
                pass
            else:
                # Wait until a frame is available
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean up
        fetcher.stop()
        cv2.destroyAllWindows()
        fetcher.logger.info("Application terminated.")
