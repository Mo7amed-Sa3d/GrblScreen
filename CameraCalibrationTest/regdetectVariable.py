from picamera2 import Picamera2
import cv2
import numpy as np

# Global variables for trackbars
threshold_val = 50
min_area_val = 500
max_area_val = 50000
circularity_val = 70  # multiplied by 100 for integer trackbar

def nothing(x):
    pass

def main():
    global threshold_val, min_area_val, max_area_val, circularity_val

    # Camera setup
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"format": 'XRGB8888', "size": (1920, 1920)})
    picam2.configure(config)
    picam2.start()

    # Create windows
    cv2.namedWindow("Live Circle Detection", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Live Circle Detection", 1024, 1024)
    cv2.namedWindow("Threshold", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Threshold", 512, 512)

    # Create trackbars
    cv2.createTrackbar("Threshold", "Threshold", threshold_val, 255, nothing)
    cv2.createTrackbar("Min Area", "Threshold", min_area_val, 20000, nothing)
    cv2.createTrackbar("Max Area", "Threshold", max_area_val, 1000000, nothing)
    cv2.createTrackbar("Circularity %", "Threshold", circularity_val, 100, nothing)

    print("Adjust trackbars to detect the circle. Press 'q' to quit.")

    while True:
        # Get current trackbar values
        threshold_val = cv2.getTrackbarPos("Threshold", "Threshold")
        min_area_val = cv2.getTrackbarPos("Min Area", "Threshold")
        max_area_val = cv2.getTrackbarPos("Max Area", "Threshold")
        circularity_val = cv2.getTrackbarPos("Circularity %", "Threshold") / 100.0

        # Capture frame
        frame = picam2.capture_array()
        bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        # Processing
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, threshold_val, 255, cv2.THRESH_BINARY_INV)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Draw contours on a copy
        output = bgr.copy()
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area_val or area > max_area_val:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)

            if circularity > circularity_val:
                # Draw detected circle
                cv2.drawContours(output, [contour], -1, (0, 255, 0), 3)
                M = cv2.moments(contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    radius = int(np.sqrt(area / np.pi))

                    # Filled overlay
                    overlay = output.copy()
                    cv2.circle(overlay, (cx, cy), radius, (255, 255, 0), -1)
                    cv2.addWeighted(overlay, 0.3, output, 0.7, 0, output)

                    # Crosshair
                    cv2.line(output, (cx - 15, cy), (cx + 15, cy), (0, 0, 255), 2)
                    cv2.line(output, (cx, cy - 15), (cx, cy + 15), (0, 0, 255), 2)

                    text = f"A:{area:.0f} C:{circularity:.2f}"
                    cv2.putText(output, text, (cx + 10, cy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                    print(f"Detected: area={area:.1f}, circularity={circularity:.2f}")

        # Show images
        cv2.imshow("Live Circle Detection", output)
        cv2.imshow("Threshold", thresh)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    picam2.stop()

if __name__ == "__main__":
    main()