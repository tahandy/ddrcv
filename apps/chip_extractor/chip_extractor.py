import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import numpy as np
from pathlib import Path
from ddrcv.state.state_matcher import StateMatcher


class ImageChipExtractorApp:
    """
    This class provides a graphical user interface (GUI) for the extraction and
    viewing of image chips from a larger image. The application contains two
    tabs: one for extracting regions of interest (ROIs) from images, and another
    for viewing saved ROIs stored as pickle files.

    The `ImageChipExtractorApp` facilitates the loading and processing of images,
    ROI selection using mouse interactions, and saving of extracted chips
    along with associated metadata. The second tab allows users to view previously
    saved image chips and their metadata.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("Image Chip Extractor")

        # Notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Extract ROI
        self.extract_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.extract_frame, text="Extract ROI")

        # Tab 2: View Saved Chip
        self.view_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.view_frame, text="View Saved Chip")

        # Tab 1: Extract ROI
        self.init_extract_tab()

        # Tab 2: View Saved Chip
        self.init_view_tab()

    def run(self):
        """Start the Tkinter main event loop."""
        self.root.mainloop()

    #######################
    # Tab 1: Extract ROI #
    #######################
    def init_extract_tab(self):
        """Initialize the 'Extract ROI' tab."""
        # Canvas for image display
        self.canvas = tk.Canvas(self.extract_frame, bg="gray")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Variables for image and ROI
        self.image = None  # PIL Image object
        self.image_tk = None  # Tkinter-compatible image
        self.image_array = None  # NumPy array representation of the image
        self.image_path = None
        self.output_dir = None  # Last used output directory

        # ROI coordinates
        self.start_x = None
        self.start_y = None
        self.end_x = None
        self.end_y = None
        self.rect_id = None

        # Add buttons
        self.add_buttons_extract_tab()

        # Bind mouse events for ROI selection
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)

    def add_buttons_extract_tab(self):
        """Add buttons to the 'Extract ROI' tab."""
        # Frame for buttons
        button_frame = tk.Frame(self.extract_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Button to load image
        load_button = tk.Button(button_frame, text="Load Image", command=self.load_image)
        load_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Button to save chip
        save_button = tk.Button(button_frame, text="Save Chip", command=self.prompt_save_chip)
        save_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Quit button
        quit_button = tk.Button(button_frame, text="Quit", command=self.root.quit)
        quit_button.pack(side=tk.RIGHT, padx=5, pady=5)

    def load_image(self):
        """Load and display an image on the canvas."""
        file_path = filedialog.askopenfilename(
            title="Select an Image",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp"), ("All files", "*.*")]
        )
        if not file_path:
            return

        # Load image, convert to NumPy array
        self.image_path = Path(file_path)
        self.image = Image.open(self.image_path)
        self.image_array = np.array(self.image)

        # Resize the canvas and window to fit the image
        self.resize_window_to_image()
        self.update_image()

    def resize_window_to_image(self):
        """Resize the window and canvas to fit the image dimensions."""
        if not self.image:
            return

        image_width, image_height = self.image.size
        padding_height = 50  # Account for buttons
        self.root.geometry(f"{image_width}x{image_height + padding_height}")
        self.canvas.config(width=image_width, height=image_height)

    def update_image(self):
        """Update the canvas with the loaded image."""
        if not self.image:
            return

        self.image_tk = ImageTk.PhotoImage(self.image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.image_tk)

    def prompt_save_chip(self):
        """Prompt user to save the selected ROI."""
        if self.image_array is None:
            messagebox.showwarning("No Image", "Please load an image first.")
            return

        if not self.rect_id:
            messagebox.showwarning("No ROI", "Please select a region of interest (ROI) first.")
            return

        selected_dir = self.output_dir or filedialog.askdirectory(title="Select Output Directory")
        if not selected_dir:
            return

        self.output_dir = Path(selected_dir)

        state_name = simpledialog.askstring("Enter State Name", "Enter name for the state:")
        if not state_name:
            return

        self.save_chip(state_name)

    def save_chip(self, state_name):
        """Save the selected ROI to a pickle file."""
        if None in (self.start_x, self.start_y, self.end_x, self.end_y):
            messagebox.showerror("Error", "The ROI coordinates are empty or undefined.")
            return

        # Normalize coordinates to ensure valid ROI selection
        x0 = min(self.start_x, self.end_x)
        y0 = min(self.start_y, self.end_y)
        x1 = max(self.start_x, self.end_x)
        y1 = max(self.start_y, self.end_y)

        # Clamp coordinates to image bounds
        x0, x1 = max(0, x0), min(self.image_array.shape[1], x1)
        y0, y1 = max(0, y0), min(self.image_array.shape[0], y1)

        # Extract the ROI (chip)
        chip = self.image_array[y0:y1, x0:x1, :]

        pkl_file_path = self.output_dir / f"{state_name}.pkl"
        if pkl_file_path.exists():
            overwrite = messagebox.askyesno("File Exists", f"{pkl_file_path.name} already exists. Overwrite?")
            if not overwrite:
                return

        # Save using StateMatcher
        try:
            matcher = StateMatcher(
                name=state_name,
                roi=(x0, y0, x1 - x0, y1 - y0),  # x, y, width, height
                rgb_glyph=chip
            )
            matcher.save(pkl_dir=self.output_dir)
            messagebox.showinfo("Success", f"State saved to {pkl_file_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save chip: {e}")

    def on_mouse_press(self, event):
        """Start tracking mouse press for ROI selection."""
        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red")

    def on_mouse_drag(self, event):
        """Track mouse movement during ROI selection."""
        self.end_x, self.end_y = event.x, event.y
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def on_mouse_release(self, event):
        """Finalize ROI selection."""
        self.end_x, self.end_y = event.x, event.y

    #################
    # Tab 2: View Saved Chip #
    #################
    def init_view_tab(self):
        """Initialize the 'View Saved Chip' tab."""
        self.view_chip_canvas = tk.Canvas(self.view_frame, bg="gray", height=400, width=400)
        self.view_chip_canvas.pack(pady=10)

        load_pickle_button = tk.Button(self.view_frame, text="Load Pickle File", command=self.load_pickled_chip)
        load_pickle_button.pack(pady=10)

        self.roi_label = tk.Label(self.view_frame, text="ROI Details: None", anchor="w", justify="left")
        self.roi_label.pack(fill=tk.X, padx=10, pady=5)

    def load_pickled_chip(self):
        """Load chip image and display its metadata."""
        file_path = filedialog.askopenfilename(
            title="Select Pickle File",
            filetypes=[("Pickle files", "*.pkl")]
        )
        if not file_path:
            return

        try:
            matcher = StateMatcher.load(file_path)

            if not isinstance(matcher, StateMatcher):
                raise ValueError("Expected a StateMatcher object.")

            chip_image = Image.fromarray(matcher.glyph)
            chip_image_tk = ImageTk.PhotoImage(chip_image)

            self.view_chip_canvas.delete("all")
            self.view_chip_canvas.create_image(0, 0, anchor=tk.NW, image=chip_image_tk)
            self.view_chip_canvas.image_tk = chip_image_tk  # Prevent garbage collection

            roi_details = f"ROI: X={matcher.roi[0]}, Y={matcher.roi[1]}, Width={matcher.roi[2]}, Height={matcher.roi[3]}"
            self.roi_label.config(text=roi_details)
        except Exception as e:
            messagebox.showerror("Error", f"Error loading pickled file: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ImageChipExtractorApp(root)
    app.run()
