from pathlib import Path

import numpy as np
from matplotlib import pyplot as plt

from state_matcher import StateMatcher
from PIL import Image


if __name__ == "__main__":
    state_template_dir = Path(r'../../state_images/')

    # file = 'caution.png'
    # name = 'caution'
    # roi = (500, 245, 275, 50)

    # file = 'gameplay.png'
    # name = 'gameplay'
    # roi = (570, 0, 140, 22)

    # file = 'song_select.png'
    # name = 'song_select'
    # file = 'song_options.png'
    # name = 'song_options'
    # roi = (0, 0, 72, 42)

    # file = 'stage_rank.png'
    # name = 'stage_rank'
    # roi = (490, 0, 300, 50)

    # file = 'song_splash_updated.png'
    # name = 'song_splash_p1'
    # roi = (66, 542, 100, 14)
    # name = 'song_splash_p2'
    # roi = (925, 542, 100, 14)


    file = 'total_result_updated.png'
    name = 'total_result'
    roi = (1018, 6, 150, 20)
    # name = 'song_splash_p2'
    # roi = (925, 542, 100, 14)

    # file = 'gameplay.png'
    # name = 'gameplay'
    # roi = (570, 0, 140, 22)

    # file = 'gameplay.png'
    # name = 'gameplay'
    # roi = (570, 0, 140, 22)

    # file = 'results_updated.png'
    # name = 'results'
    # roi = (490, 10, 300, 58)

    image = Image.open(state_template_dir / file)
    image = np.array(image)

    plt.imshow(image)
    plt.show()

    chip = image[roi[1]:roi[1] + roi[3], roi[0]:roi[0] + roi[2], ...]

    plt.imshow(chip)
    plt.show()

    matcher = StateMatcher(name, roi, chip, threshold_distance=5)
    matcher.save()






