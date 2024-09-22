from pathlib import Path
import cv2
import os


class VideoFrameExtractor:
    def __init__(self, video_path):
        self.video_path = video_path

        # Check if the file exists
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Attempt to open the video file
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")

        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        self.height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"Video opened successfully: {video_path}")
        print(f"Total frames: {self.total_frames}, FPS: {self.fps}")

    def get_frame_by_index(self, index):
        """Get frame by index."""
        if index < 0 or index >= self.total_frames:
            raise IndexError(f"Index out of range. Must be between 0 and {self.total_frames-1}")

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ret, frame = self.cap.read()
        if not ret:
            raise ValueError(f"Failed to read the frame at index {index}")

        return frame

    def get_frame_index_by_time(self, time_seconds):
        frame_index = int(time_seconds * self.fps)
        return frame_index

    def get_frame_by_time(self, time_seconds):
        """Get frame by time in seconds."""
        frame_index = int(time_seconds * self.fps)
        return self.get_frame_by_index(frame_index)

    def preload_frames(self, start_index, end_index):
        """
        Preload a range of frames into memory for faster access.

        :param start_index: The starting index of the frame range.
        :param end_index: The ending index of the frame range.
        :return: List of preloaded frames.
        """
        if start_index < 0 or end_index >= self.total_frames or start_index > end_index:
            raise IndexError(f"Frame range out of bounds. Must be between 0 and {self.total_frames-1} and start_index <= end_index")

        preloaded_frames = []

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_index)
        for i in range(start_index, end_index + 1):
            ret, frame = self.cap.read()
            if not ret:
                raise ValueError(f"Failed to read the frame at index {i}")
            preloaded_frames.append(frame)

        return preloaded_frames

    def release(self):
        """Release the video capture object."""
        self.cap.release()

    def __del__(self):
        """Ensure resources are released when the object is deleted."""
        self.release()



# Usage example
if __name__ == "__main__":

    video_file = Path(r"C:\code\ddr_ex_parser\videos\Dr.D's DDR WORLD Stream # 3 (08 05 24).mp4")
    # video_file = Path(r"C:\code\ddr_ex_parser\second.mp4")
    print(video_file.exists())
    extractor = VideoFrameExtractor(str(video_file))

    # Get a frame by index
    # frame_by_index = extractor.get_frame_by_index(100)
    # cv2.imwrite("frame_by_index.jpg", frame_by_index)

    # Get a frame by time
    # for ii in range(30):
    #     frame_by_time = extractor.get_frame_by_time(ii + 4287)
    #     frame_by_index = extractor.get_frame_by_time(ii + 4287)
    #     cv2.imwrite(f"splash_{ii}.png", frame_by_time)

    frame_by_time = extractor.get_frame_by_time(350)
    cv2.imwrite(f"the_ashes_of_boreas.png", frame_by_time)
    # Release resources
    extractor.release()
