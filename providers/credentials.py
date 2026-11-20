"""The error every provider raises when it has no usable credential."""


class MissingCredentialError(Exception):
    """The configured provider cannot sign in; the message says what to set or run."""
