import imagehash
from PIL import Image

import matplotlib.pyplot as plt


class HashMatcher:
    def __init__(self, template_image, threshold_distance=5):
        self.template = Image.fromarray(template_image).convert('L')
        self.template_hash = imagehash.dhash(self.template)
        self.threshold = threshold_distance

    def match(self, target_image):
        target_hash = imagehash.dhash(Image.fromarray(target_image).convert('L'))

        # fig, ax = plt.subplots(1, 2)
        # ax[0].imshow(Image.fromarray(target_image).convert('L'))
        # ax[1].imshow(self.template)
        # plt.show()

        # print('diff: ', self.template_hash - target_hash)
        return (self.template_hash - target_hash) < self.threshold

    def match_roi(self, target_image, roi):
        """

        :param target_image:
        :param roi: (x, y, w, h)
        :return:
        """
        return self.match(target_image[roi[1]:roi[1] + roi[3], roi[0]:roi[0] + roi[2], ...])
