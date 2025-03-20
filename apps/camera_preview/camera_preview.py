import cv2


if __name__ == "__main__":
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    initialized = False
    window_name = 'Press "q" to close'

    while True:
        ret, frame = cap.read()
        print(frame.shape)
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