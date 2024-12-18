import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import numpy as np
from pathlib import Path
from ddrcv.state.state_matcher import StateMatcher


class ImageChipExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Chip Extractor")

        # Canvas for image display
        self.canvas = tk.Canvas(root, bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Variables for image and ROI
        self.image = None  # PIL Image object
        self.image_tk = None  # Tkinter-compatible image
        self.image_array = None  # Numpy array representation of the image
        self.image_path = None

        # Last used output directory
        self.output_dir = None

        # Variables for ROI (Region of Interest)
        self.start_x = None
        self.start_y = None
        self.end_x = None
        self.end_y = None
        self.rect_id = None

        # Add buttons
        self.add_buttons()

        # Bind mouse events for ROI selection
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)

    def add_buttons(self):
        # Frame for buttons
        button_frame = tk.Frame(self.root)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Load Image Button
        load_button = tk.Button(button_frame, text="Load Image", command=self.load_image)
        load_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Save Chip Button
        save_button = tk.Button(button_frame, text="Save Chip", command=self.prompt_save_chip)
        save_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Quit Button
        quit_button = tk.Button(button_frame, text="Quit", command=self.root.quit)
        quit_button.pack(side=tk.RIGHT, padx=5, pady=5)

    def load_image(self):
        # Open a file dialog to select an image
        file_path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp"), ("All files", "*.*")]
        )
        if not file_path:
            return

        # Load image using PIL and convert to a NumPy array
        self.image_path = Path(file_path)
        self.image = Image.open(self.image_path)
        self.image_array = np.array(self.image)

        # Resize the window to fit the image dimensions
        self.resize_window_to_image()

        # Display the loaded image
        self.update_image()

    def resize_window_to_image(self):
        """Resize the window to fit the dimensions of the loaded image."""
        if self.image is None:
            return

        # Get the dimensions of the loaded image
        image_width, image_height = self.image.size

        # Add some padding to account for buttons/frame
        padding_height = 50  # Adjust for button height
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        # Ensure the window does not exceed the screen dimensions
        window_width = min(image_width, screen_width)
        window_height = min(image_height + padding_height, screen_height)

        # Resize the window
        self.root.geometry(f"{window_width}x{window_height}")

        # Adjust the canvas to fit the image
        self.canvas.config(width=image_width, height=image_height)

    def update_image(self):
        if self.image is None:
            return

        # Convert the image to a Tkinter-compatible object
        self.image_tk = ImageTk.PhotoImage(self.image)

        # Display the image on the canvas
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.image_tk)

    def prompt_save_chip(self):
        if self.image_array is None:
            messagebox.showwarning("No Image", "Please load an image before saving.")
            return

        if not self.rect_id:
            messagebox.showwarning("No ROI", "Please select a region of interest (ROI) before saving.")
            return

        # Select output directory
        selected_dir = self.output_dir or filedialog.askdirectory(title="Select Output Directory")
        if not selected_dir:
            return

        self.output_dir = Path(selected_dir)  # Remember the directory

        # Prompt for the state name
        state_name = simpledialog.askstring("Enter State Name", "Enter the state name:", parent=self.root)
        if not state_name:
            return

        # Save the chip
        self.save_chip(state_name)

    def save_chip(self, state_name):
        if self.start_x is None or self.start_y is None or self.end_x is None or self.end_y is None:
            messagebox.showerror("Error", "The ROI coordinates are not properly defined.")
            return

        # Convert canvas ROI to image coordinates
        x0, x1 = sorted([self.start_x, self.end_x])
        y0, y1 = sorted([self.start_y, self.end_y])

        # Calculate width and height of ROI
        w, h = x1 - x0, y1 - y0
        roi = (x0, y0, w, h)

        # Validate ROI boundaries
        if x0 < 0 or y0 < 0 or x1 > self.image_array.shape[1] or y1 > self.image_array.shape[0]:
            messagebox.showerror("Error", "ROI coordinates are out of bounds.")
            return

        # Extract the chip as a NumPy array
        chip = self.image_array[y0:y1, x0:x1, :]

        # Create the target file path
        pkl_file_path = self.output_dir / f"{state_name}.pkl"

        # Check if the file already exists
        if pkl_file_path.exists():
            overwrite = messagebox.askyesno(
                "File Exists",
                f"The file '{pkl_file_path.name}' already exists.\nDo you want to overwrite it?",
            )
            if not overwrite:
                return  # Do not proceed with saving

        try:
            # Create StateMatcher and save
            matcher = StateMatcher(
                name=state_name,
                roi=roi,
                rgb_glyph=chip,
                threshold_distance=5
            )
            matcher.save(pkl_dir=self.output_dir)

            messagebox.showinfo("Success", f"Chip and ROI successfully saved to: {self.output_dir}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while saving the chip: {e}")

    def on_mouse_press(self, event):
        # Start drawing the ROI rectangle
        self.start_x = event.x
        self.start_y = event.y

        # Remove any existing rectangle
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline='red'
        )

    def on_mouse_drag(self, event):
        # Update the rectangle while dragging
        if self.rect_id:
            self.end_x = event.x
            self.end_y = event.y
            self.canvas.coords(
                self.rect_id,
                self.start_x,
                self.start_y,
                event.x,
                event.y,
            )

    def on_mouse_release(self, event):
        # Finalize the rectangle
        if self.rect_id:
            self.end_x = event.x
            self.end_y = event.y

    def run(self):
        # Start the Tkinter main loop
        self.root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageChipExtractorApp(root)
    app.run()
