# coding=utf-8
# Copyright 2018 The TensorFlow Datasets Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# coding=utf-8
"""TextEncoders convert between text and integers."""

import abc
import hashlib
import re

import six
import tensorflow as tf

# TODO(rsepassi):
# * Add support for reserved tokens (PAD, EOS, etc.) to TextEncoder
# * Determine how to handle PAD/START/END
# * Add SubwordTextEncoder


@six.add_metaclass(abc.ABCMeta)
class TextEncoder(object):
  """Abstract base class for converting between text and integers."""

  @abc.abstractmethod
  def encode(self, s):
    """Encodes text into a list of integers."""
    raise NotImplementedError

  @abc.abstractmethod
  def decode(self, ids):
    """Decodes a list of integers into text."""
    raise NotImplementedError

  @abc.abstractproperty
  def vocab_size(self):
    raise NotImplementedError


class ByteTextEncoder(TextEncoder):
  """Byte-encodes text."""

  def encode(self, s):
    return list(bytearray(tf.compat.as_bytes(s)))

  def decode(self, ids):
    return tf.compat.as_text(bytes(bytearray(ids)))

  @property
  def vocab_size(self):
    return 2**8


class TokenTextEncoder(TextEncoder):
  r"""TextEncoder backed by a list of tokens.

  Tokenization splits on (and drops) non-alphanumeric characters with
  regex "\W+".
  """

  def __init__(self,
               vocab_list=None,
               vocab_file=None,
               oov_buckets=1,
               oov_token=u"UNK"):
    """Constructs a TokenTextEncoder.

    Must pass either `vocab_list` or `vocab_file`.

    Args:
      vocab_list: `list<str>`, list of tokens.
      vocab_file: `str`, filepath with 1 token per line.
      oov_buckets: `int`, the number of `int`s to reserve for OOV hash buckets.
        Tokens that are OOV will be hash-modded into a OOV bucket in `encode`.
      oov_token: `str`, the string to use for OOV ids in `decode`.
    """
    if not (vocab_list or vocab_file) or (vocab_list and vocab_file):
      raise ValueError("Must provide either vocab_list or vocab_file.")
    self._vocab_list = [
        tf.compat.as_text(el).strip() for el in
        vocab_list or self._load_tokens_from_file(vocab_file)
    ]
    self._token_to_id = dict(
        zip(self._vocab_list, range(len(self._vocab_list))))
    self._oov_buckets = oov_buckets
    self._oov_token = tf.compat.as_text(oov_token)
    self._tokenizer = Tokenizer()

  def encode(self, s):
    ids = []
    for token in self._tokenizer.tokenize(tf.compat.as_text(s)):
      int_id = self._token_to_id.get(token, -1)
      if int_id < 0:
        int_id = self._oov_bucket(token)
        if int_id is None:
          raise ValueError("Out of vocabulary token %s" % token)
      ids.append(int_id)
    return ids

  def decode(self, ids):
    tokens = []
    for int_id in ids:
      if int_id < len(self._vocab_list):
        tokens.append(self._vocab_list[int_id])
      else:
        tokens.append(self._oov_token)
    return u" ".join(tokens)

  @property
  def vocab_size(self):
    return len(self._vocab_list) + self._oov_buckets

  @property
  def tokens(self):
    return list(self._vocab_list)

  def store_to_file(self, fname):
    with tf.gfile.Open(fname, "wb") as f:
      f.write(tf.compat.as_bytes(u"\n".join(self._vocab_list)))

  def _oov_bucket(self, token):
    if self._oov_buckets <= 0:
      return None
    if self._oov_buckets == 1:
      return len(self._vocab_list)
    hash_val = int(hashlib.md5(tf.compat.as_bytes(token)).hexdigest(), 16)
    return len(self._vocab_list) + hash_val % self._oov_buckets

  def _load_tokens_from_file(self, fname):
    with tf.gfile.Open(fname, "rb") as f:
      return [el.strip() for el in tf.compat.as_text(f.read()).split(u"\n")]


class Tokenizer(object):
  """Splits a string into tokens, and joins them back."""

  def __init__(self, alphanum_only=True, reserved_tokens=None):
    """Constructs a Tokenizer.

    Note that the Tokenizer is invertible if `alphanum_only=False`.
    i.e. `s == t.join(t.tokenize(s))`.

    Args:
      alphanum_only: `bool`, if `True`, only parse out alphanumeric tokens
        (non-alphanumeric characters are dropped);
        otherwise, keep all characters (individual tokens will still be either
        all alphanumeric or all non-alphanumeric).
      reserved_tokens: `list<str>`, a list of strings that, if any are in `s`,
        will be preserved as whole tokens, even if they contain mixed
        alphnumeric/non-alphanumeric characters.
    """
    self._alphanum_only = alphanum_only
    self._reserved_tokens = set(
        [tf.compat.as_text(tok) for tok in reserved_tokens or []])
    if self._reserved_tokens:
      pattern = u"(%s)" % u"|".join(reserved_tokens)
      self._reserved_tokens_re = re.compile(pattern, flags=re.UNICODE)

    if self._alphanum_only:
      pattern = r"\W+"
    else:
      pattern = r"(\W+)"
    self._alphanum_re = re.compile(pattern, flags=re.UNICODE)

  def tokenize(self, s):
    """Splits a string into tokens."""
    reserved_tokens = self._reserved_tokens

    s = tf.compat.as_text(s)

    if reserved_tokens:
      # First split out the reserved tokens
      substrs = self._reserved_tokens_re.split(s)
    else:
      substrs = [s]

    toks = []
    for substr in substrs:
      if substr in reserved_tokens:
        toks.append(substr)
      else:
        toks.extend(self._alphanum_re.split(substr))

    # Filter out empty strings
    toks = [t for t in toks if t]
    return toks

  def join(self, tokens):
    """Joins tokens into a string."""
    if self._alphanum_only:
      return u" ".join(tokens)
    else:
      # Fully invertible
      return u"".join(tokens)