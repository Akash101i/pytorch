import torch
import sys
from collections import OrderedDict

# pattern for conv bn fusion
FUSION_PATTERNS = OrderedDict()
def register_fusion_pattern(pattern):
    def insert(fn):
        FUSION_PATTERNS[pattern] = fn
        return fn
    return insert

def get_fusion_patterns():
    return FUSION_PATTERNS

QUANTIZATION_PATTERNS = OrderedDict()
# a map from pattern to activation_post_process(observer/fake_quant) consstructor for output activation
# e.g. pattern: torch.sigmoid,
#      output_activation_post_process: default_affine_fixed_qparam_fake_quant
OUTPUT_ACTIVATION_POST_PROCESS_MAP = dict()

# Register pattern for both static quantization and qat
#
def register_quant_pattern(pattern, output_activation_post_process=None):
    def insert(fn):
        QUANTIZATION_PATTERNS[pattern] = fn
        if output_activation_post_process is not None:
            OUTPUT_ACTIVATION_POST_PROCESS_MAP[pattern] = output_activation_post_process
        return fn
    return insert

# Get patterns for both static quantization and qat
def get_quant_patterns():
    return QUANTIZATION_PATTERNS

# a map from pattern to output activation post process constructor
# e.g. torch.sigmoid -> default_affine_fixed_qparam_fake_quant
def get_output_activation_post_process_map():
    return OUTPUT_ACTIVATION_POST_PROCESS_MAP

# Example use of register pattern function:
# @register_fusion_pattern(torch.nn.ReLU, (torch.nn.BatchNorm2d, torch.nn.Conv2d)))
# class ConvBNReLUFusion():
#     def __init__(...):
#         ...
#
# Note: The order of patterns is important! match function will take whatever is matched first, so we'll
# need to put the fusion patterns before single patterns. For example, add_relu should be registered come before relu.
# decorators are applied in the reverse order we see. Also when we match the nodes in the graph with these patterns,
# we'll start from the last node of the graph and traverse back.

def is_match(modules, node, pattern, max_uses=sys.maxsize):
    """ Matches a node in fx against a pattern
    """
    if isinstance(pattern, tuple):
        self_match, *arg_matches = pattern
        if self_match is getattr:
            assert len(pattern) == 2, 'Expecting getattr pattern to have two elements'
            arg_matches = []
    else:
        self_match = pattern
        arg_matches = []

    if node.uses > max_uses:
        return False

    if isinstance(self_match, type) and issubclass(self_match, torch.nn.Module):
        if node.op != 'call_module':
            return False
        if not type(modules[node.target]) == self_match:
            return False
    elif callable(self_match):
        if node.op != 'call_function' or node.target is not self_match:
            return False
        elif node.target is getattr:
            if node.args[1] != pattern[1]:
                return False
    elif isinstance(self_match, str):
        if node.op != 'call_method' or node.target != self_match:
            return False
    elif node.target != self_match:
        return False

    if not arg_matches:
        return True

    if len(arg_matches) != len(node.args):
        return False

    return all(is_match(modules, node, arg_match, max_uses=1) for node, arg_match in zip(node.args, arg_matches))
