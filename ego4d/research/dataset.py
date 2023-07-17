import bisect
import os
import math
from typing import Any, Callable, List, Optional, Tuple, Dict

from tqdm.auto import tqdm

import h5py
import torch
from ego4d.research.readers import PyAvReader, TorchAudioStreamReader, StridedReader



class LabelledFeatureDset(torch.utils.data.Dataset):
    """
    A simple utility class to load features associated with labels. The input this
    method requires is as follows:
        1. `feature_hdf5_path`: the features transposed to a HDF5 file.
            See `save_ego4d_features_to_hdf5`
        2. `uid_label_pairs` a list of (uid, label). `label` can be anything
            `uid` is a unique id associated to the `feature_hdf5_path` file.
        3. `aggr_function` a function to aggregate based off given label
    """

    def __init__(
        self,
        feature_hdf5_path: str,
        uid_label_pairs: List[Tuple[str, Any]],
        aggr_function: Optional[Callable[[torch.Tensor, Any], torch.Tensor]] = None,
    ):
        self.uid_label_pairs = uid_label_pairs
        self.features = h5py.File(feature_hdf5_path)
        self.aggr_function = (
            aggr_function
            if aggr_function is not None
            else lambda x, _: torch.tensor(x[0:]).squeeze()
        )

    def __len__(self):
        return len(self.uid_label_pairs)

    def __getitem__(self, idx: int):
        uid, label = self.uid_label_pairs[idx]
        feat = self.aggr_function(self.features[uid], label)
        return feat, label

def save_ego4d_features_to_hdf5(video_uids: List[str], feature_dir: str, out_path: str):
    """
    Use this function to preprocess Ego4D features into a HDF5 file with h5py
    """
    with h5py.File(out_path, "w") as out_f:
        for uid in tqdm(video_uids, desc="video_uid", leave=True):
            feature_path = os.path.join(feature_dir, f"{uid}.pt")
            fv = torch.load(feature_path)
            out_f.create_dataset(uid, data=fv.numpy())


# essentially a lazy ConcatDataset
# https://pytorch.org/docs/stable/_modules/torch/utils/data/dataset.html#ConcatDataset
class VideoDataset:
    def __init__(
        self,
        paths: List[str],
        video_class: type,
        video_class_kwargs: Dict[str, Any],
        max_num_frames_per_video: Optional[int] = None,
        paths_to_n_frames: Optional[Dict[str, int]] = None,
        with_pbar: bool = False,
    ):
        paths = sorted(paths)
        self.video_class = video_class
        self.video_class_kwargs = video_class_kwargs
        self.paths = paths
        if paths_to_n_frames is None:
            breakpoint()
            print("Creating containers")
            path_iter = paths
            if with_pbar:
                path_iter = tqdm(paths)
            self.conts = {
                idx: (p, video_class(p, **video_class_kwargs))
                for idx, p in enumerate(path_iter)
            }
            print("Created containers")

            cont_iter = list(self.conts.values())
            if with_pbar:
                cont_iter = tqdm(cont_iter)

            self.fs_cumsum = [ 
                min(len(ct), max_num_frames_per_video)
                if max_num_frames_per_video else len(ct)
                for _, ct in cont_iter
            ]
            self.fs_cumsum = [0] + torch.cumsum(torch.tensor(self.fs_cumsum), dim=0).tolist()
        else:
            self.fs_cumsum = [ 
                paths_to_n_frames[path] for path in paths
            ]
            self.fs_cumsum = [0] + torch.cumsum(torch.tensor(self.fs_cumsum), dim=0).tolist()
            self.conts = {
                idx: (p, None)
                for idx, p in enumerate(paths)
            }


    def __getitem__(self, i):
        cont_idx = bisect.bisect_left(self.fs_cumsum, i + 1) - 1
        p, c = self.conts[cont_idx]
        if c is None:
            self.conts[cont_idx] = (p, self.video_class(p, **self.video_class_kwargs))
        _, c = self.conts[cont_idx]
        assert c is not None
        idx = i - self.fs_cumsum[cont_idx]
        return c[idx]

    def __len__(self):
        return self.fs_cumsum[-1]
