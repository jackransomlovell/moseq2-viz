from collections import defaultdict, OrderedDict
from copy import deepcopy
from moseq2_viz.util import h5_to_dict
import numpy as np
import h5py
import pandas as pd
import networkx as nx
import warnings
import tqdm


def convert_ebunch_to_graph(ebunch):

    g = nx.Graph()
    g.add_weighted_edges_from(ebunch)

    return g


def convert_transition_matrix_to_ebunch(transition_matrix, edge_threshold=1, indices=None):

    if indices is None:
        ebunch = [(i[0], i[1], v) for i, v in np.ndenumerate(transition_matrix)
                  if np.abs(v) > edge_threshold]
    else:
        ebunch = [(i[0], i[1], transition_matrix[i[0], i[1]]) for i in indices]

    return ebunch


# per https://gist.github.com/tg12/d7efa579ceee4afbeaec97eb442a6b72
def get_transition_matrix(labels, max_syllable=100, normalize='bigram', smoothing=1.0, combine=False):

    if combine:
        init_matrix = np.zeros((max_syllable, max_syllable), dtype='float32')

        for v in labels:

            transitions, _ = get_transitions(v)

            for (i, j) in zip(transitions, transitions[1:]):
                if i < max_syllable and j < max_syllable:
                    init_matrix[i, j] += 1

        if normalize == 'bigram':
            init_matrix /= init_matrix.sum()
        elif normalize == 'rows':
            init_matrix /= init_matrix.sum(axis=1) + smoothing
        elif normalize == 'columns':
            init_matrix /= init_matrix.sum(axis=0) + smoothing
        else:
            pass

        all_mats = init_matrix
    else:

        all_mats = []
        for v in tqdm.tqdm(labels):

            init_matrix = np.zeros((max_syllable, max_syllable), dtype='float32')
            transitions, _ = get_transitions(v)

            for (i, j) in zip(transitions, transitions[1:]):
                if i < max_syllable and j < max_syllable:
                    init_matrix[i, j] += 1

        if normalize == 'bigram':
            init_matrix /= init_matrix.sum()
        elif normalize == 'rows':
            init_matrix /= init_matrix.sum(axis=1) + smoothing
        elif normalize == 'columns':
            init_matrix /= init_matrix.sum(axis=0) + smoothing
        else:
            pass

        all_mats.append(init_matrix)

    return all_mats


def get_syll_durations(data, fill_value=-5, max_syllable=100):
    return get_syllable_statistics(data, fill_value=fill_value, max_syllable=max_syllable)[1]


# return tuples with uuid and syllable indices
def get_syllable_slices(syllable, labels, label_uuids, index, trim_nans=True):

    h5s = [v['path'][0] for v in index['files'].values()]
    h5_uuids = list(index['files'].keys())

    # grab the original indices from the pca file as well...

    if trim_nans:
        with h5py.File(index['pca_path'], 'r') as f:
            score_idx = h5_to_dict(f, 'scores_idx')

    sorted_h5s = [h5s[h5_uuids.index(uuid)] for uuid in label_uuids]
    syllable_slices = []

    for label_arr, label_uuid, h5 in zip(labels, label_uuids, sorted_h5s):

        if trim_nans:
            idx = score_idx[label_uuid]

            if len(idx) > len(label_arr):
                idx = idx[:len(label_arr)]
            elif len(idx) < len(label_arr):
                warnings.warn('Index length {:d} and label array length {:d} in {}'
                              .format(len(idx), len(label_arr), h5))
                continue

            trim_idx = idx[~np.isnan(idx)].astype('int32')
            label_arr = label_arr[~np.isnan(idx)]
        else:
            trim_idx = np.arange(len(label_arr))

        match_idx = trim_idx[np.where(label_arr == syllable)[0]]
        breakpoints = np.where(np.diff(match_idx, axis=0) > 1)[0]

        if len(breakpoints) < 1:
            continue

        breakpoints = zip(np.r_[0, breakpoints+1], np.r_[breakpoints, len(breakpoints)-1])
        for i, j in breakpoints:
            syllable_slices.append([(match_idx[i], match_idx[j]), label_uuid, h5])

    return syllable_slices


def get_syllable_statistics(data, fill_value=-5, max_syllable=100):

    # if type(data) is list and type(data[0]) is np.ndarray:
    #     data = np.array([np.squeeze(tmp) for tmp in data], dtype='object')

    usages = defaultdict(int)
    durations = defaultdict(list)

    for s in range(max_syllable):
        usages[s] = 0
        durations[s] = []

    if type(data) is list:

        for v in data:
            seq_array, locs = get_transitions(v)
            to_rem = np.where(seq_array > max_syllable)[0]

            seq_array = np.delete(seq_array, to_rem)
            locs = np.delete(locs, to_rem)

            durs = np.diff(locs)

            for s, d in zip(seq_array, durs):
                usages[s] += 1
                durations[s].append(d)

    elif type(data) is np.ndarray and data.dtype == 'int16':

        seq_array, locs = get_transitions(data)
        to_rem = np.where(seq_array > max_syllable)[0]
        seq_array = np.delete(seq_array, to_rem)
        locs = np.delete(locs, to_rem)
        durs = np.diff(locs)

        for s, d in zip(seq_array, durs):
            usages[s] += 1
            durations[s].append(d)

    usages = OrderedDict(sorted(usages.items()))
    durations = OrderedDict(sorted(durations.items()))

    return usages, durations


def get_transitions(label_sequence):

    arr = deepcopy(label_sequence)
    arr = np.insert(arr, len(arr), -10)
    locs = np.where(arr[1:] != arr[:-1])[0]+1
    transitions = arr[locs][:-1]
    return transitions, locs


def parse_batch_modeling(filename):

    with h5py.File(filename, 'r') as f:
        results_dict = {
            'heldouts': np.squeeze(f['metadata/heldout_ll'].value),
            'parameters': h5_to_dict(f, 'metadata/parameters'),
            'scans': h5_to_dict(f, 'scans'),
            'filenames': f['filenames'].value,
            'labels': np.squeeze(f['labels'].value),
            'label_uuids': [str(_, 'utf-8') for _ in f['/metadata/train_list'].value]
        }
        results_dict['scan_parameters'] = {k: results_dict['parameters'][k]
                                           for k in results_dict['scans'].keys()}

    return results_dict


def parse_model_results(model_obj, restart_idx=0):

    # reformat labels into something useful

    output_dict = model_obj
    if type(output_dict['labels']) is list and type(output_dict['labels'][0]) is list:
        output_dict['labels'] = [np.squeeze(tmp) for tmp in output_dict['labels'][restart_idx]]

    return output_dict


def relabel_by_usage(labels):

    sorted_labels = deepcopy(labels)
    usages, durations = get_syllable_statistics(labels)
    sorting = []

    for w in sorted(usages, key=usages.get, reverse=True):
        sorting.append(w)

    for i, v in enumerate(labels):
        for j, idx in enumerate(sorting):
            sorted_labels[i][np.where(v == idx)] = j

    return sorted_labels


def results_to_dataframe(model_dict, index_dict, sort=False, normalize=True, max_syllable=40,
                         include_meta=['SessionName', 'SubjectName', 'StartTime']):

    if sort:
        model_dict['labels'] = relabel_by_usage(model_dict['labels'])

    # by default the keys are the uuids

    if 'train_list' in model_dict.keys():
        label_uuids = model_dict['train_list']
    else:
        label_uuids = model_dict['keys']

    # durations = []

    df_dict = {
            'usage': [],
            'group': [],
            'syllable': []
        }

    for key in include_meta:
        df_dict[key] = []

    groups = [index_dict['files'][uuid]['group'] for uuid in label_uuids]
    metadata = [index_dict['files'][uuid]['metadata'] for uuid in label_uuids]

    for i, label_arr in enumerate(model_dict['labels']):
        tmp_usages, tmp_durations = get_syllable_statistics(label_arr, max_syllable=max_syllable)
        total_usage = np.sum(list(tmp_usages.values()))

        for k, v in tmp_usages.items():
            df_dict['usage'].append(v / total_usage)
            df_dict['syllable'].append(k)
            df_dict['group'].append(groups[i])

            for meta_key in include_meta:
                df_dict[meta_key].append(metadata[i][meta_key])

    df = pd.DataFrame.from_dict(data=df_dict)

    return df, df_dict


def sort_batch_results(data, averaging=True, **kwargs):

    parameters = np.hstack(kwargs.values())
    param_sets = np.unique(parameters, axis=0)
    param_dict = {k: np.unique(v[np.isfinite(v)]) for k, v in kwargs.items()}

    param_list = list(param_dict.values())
    param_list = [p[np.isfinite(p)] for p in param_list]
    new_shape = tuple([len(v) for v in param_list])

    new_matrix = np.zeros(new_shape, dtype=data.dtype)
    new_count = np.zeros(new_shape, dtype=data.dtype)

    dims = len(new_shape)

    if dims > 2:
        raise NotImplementedError('No support for more than 2 dimensions')

    if not averaging:
        raise NotImplementedError('Only averaging restarts is supported')

    # TODO: add support for no averaging (just default_dict or list)

    for param in param_sets:
        row_matches = np.where((parameters == param).all(axis=1))[0]
        idx = np.zeros((len(param),), dtype='int')

        if np.any(np.isnan(param)):
            continue

        for i, p in enumerate(param):
            idx[i] = int(np.where(param_list[i] == p)[0])

        for row in row_matches:
            if dims == 2:
                if idx[0] > 0 and idx[1] > 0:
                    new_matrix[idx[0], idx[1]] = data[row]
                    new_count[idx[0], idx[1]] += 1
            elif dims == 1:
                if idx > 0:
                    new_matrix[idx] += data[row]
                    new_count[idx] += 1

    new_matrix[new_count == 0] = np.nan

    if averaging:
        new_matrix /= new_count

    return new_matrix, param_dict
