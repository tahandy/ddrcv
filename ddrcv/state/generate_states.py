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

    # file = 'song_splash.png'
    # name = 'song_splash_p1'
    # roi = (64, 535, 100, 25)
    # name = 'song_splash_p2'
    # roi = (924, 535, 100, 25)

    # file = 'gameplay.png'
    # name = 'gameplay'
    # roi = (570, 0, 140, 22)

    image = Image.open(state_template_dir / file)
    image = np.array(image)
    #
    # plt.imshow(image)
    # plt.show()


    matcher = StateMatcher(name, roi, image[roi[1]:roi[1] + roi[3], roi[0]:roi[0] + roi[2], ...], threshold_distance=5)
    matcher.save()






