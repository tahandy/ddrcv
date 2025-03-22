import cv2
from cv2_enumerate_cameras import enumerate_cameras


if __name__ == "__main__":
    camera_uri = 0
    valid_indices = []
    print('Available cameras:')
    for camera_info in enumerate_cameras(cv2.CAP_DSHOW):
        print(f'{camera_info.index}: {camera_info.name}')
        valid_indices.append(camera_info.index)

    while True:
        user_input = input("Enter camera index: ")
        value = None
        try:
            value = int(user_input)
        except ValueError:
            print("Invalid input. Please enter a valid integer.")
        else:
            if value in valid_indices:
                camera_uri = value
                break
            print(f"Invalid input. Please enter a valid camera index from the list {valid_indices}.")

    cap = cv2.VideoCapture(camera_uri, cv2.CAP_DSHOW)
    initialized = False
    window_name = 'Press "q" to close'

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to capture frame")
            break

        if not initialized:
            # Create a named window with WINDOW_NORMAL flag
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            # Resize the window to the image dimensions
            cv2.resizeWindow(window_name, frame.shape[1], frame.shape[0])
            initialized = True

        cv2.imshow(window_name, frame)

        # Break loop if 'q' is pressed
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()