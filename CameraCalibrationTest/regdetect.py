from picamera2 import Picamera2
import cv2
import numpy as np

# Detection parameters (based on your successful run)
THRESHOLD = 100
MIN_AREA = 100000      # slightly below your measured area
MAX_AREA = 400000      # slightly above your measured area
CIRCULARITY_MIN = 0.7   # 0.88 is well above this
BLUR_KERNEL = (5, 5)

def main():
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"format": 'XRGB8888', "size": (1920, 1920)}
    )
    picam2.configure(config)
    picam2.start()

    cv2.namedWindow("Circle Detection", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Circle Detection", 1024, 1024)

    print("Press 'q' to quit.")

    while True:
        frame = picam2.capture_array()
        bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, BLUR_KERNEL, 0)
        _, thresh = cv2.threshold(blurred, THRESHOLD, 255, cv2.THRESH_BINARY_INV)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        output = bgr.copy()
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < MIN_AREA or area > MAX_AREA:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)

            if circularity > CIRCULARITY_MIN:
                cv2.drawContours(output, [contour], -1, (0, 255, 0), 3)

                M = cv2.moments(contour)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    radius = int(np.sqrt(area / np.pi))

                    # Draw filled overlay
                    overlay = output.copy()
                    cv2.circle(overlay, (cx, cy), radius, (255, 255, 0), -1)
                    cv2.addWeighted(overlay, 0.3, output, 0.7, 0, output)

                    # Draw crosshair at center
                    cv2.line(output, (cx - 15, cy), (cx + 15, cy), (0, 0, 255), 2)
                    cv2.line(output, (cx, cy - 15), (cx, cy + 15), (0, 0, 255), 2)

                    # Display area, circularity, and coordinates
                    info_text = f"A:{area:.0f} C:{circularity:.2f}"
                    coord_text = f"({cx}, {cy})"
                    cv2.putText(output, info_text, (cx + 10, cy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                    cv2.putText(output, coord_text, (cx + 10, cy + 20),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                    print(f"Circle detected: center=({cx}, {cy}), area={area:.0f}, circularity={circularity:.2f}")

        cv2.imshow("Circle Detection", output)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    picam2.stop()

if __name__ == "__main__":
    main()