class FileAutomationException(Exception):
    pass


class FileNotExistsException(FileAutomationException):
    pass


class DirNotExistsException(FileAutomationException):
    pass


class ZIPGetWrongFileException(FileAutomationException):
    pass


class CallbackExecutorException(FileAutomationException):
    pass


class ExecuteActionException(FileAutomationException):
    pass


class AddCommandException(FileAutomationException):
    pass


class JsonActionException(FileAutomationException):
    pass


class ArgparseException(FileAutomationException):
    pass
