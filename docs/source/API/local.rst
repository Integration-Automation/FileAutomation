Local file api
----

.. code-block:: python

    def copy_dir(dir_path: str, target_dir_path: str) -> bool:
        """
        Copy dir to target path (path need as dir path)
        :param dir_path: which dir do we want to copy (str path)
        :param target_dir_path: copy dir to this path
        :return: True if success else False
        """

.. code-block:: python

    def remove_dir_tree(dir_path: str) -> bool:
        """
        :param dir_path: which dir do we want to remove (str path)
        :return: True if success else False
        """

.. code-block:: python

    def rename_dir(origin_dir_path, target_dir: str) -> bool:
        """
        :param origin_dir_path: which dir do we want to rename (str path)
        :param target_dir: target name as str full path
        :return: True if success else False
        """

.. code-block:: python

    def create_dir(dir_path: str) -> None:
        """
        :param dir_path: create dir on dir_path
        :return: None
        """

.. code-block:: python


    def copy_file(file_path: str, target_path: str) -> bool:
        """
        :param file_path: which file do we want to copy (str path)
        :param target_path: put copy file on target path
        :return: True if success else False
        """

.. code-block:: python

    def copy_specify_extension_file(file_dir_path: str, target_extension: str, target_path: str) -> bool:
        """
        :param file_dir_path: which dir do we want to search
        :param target_extension: what extension we will search
        :param target_path: copy file to target path
        :return: True if success else False
        """

.. code-block:: python

    def copy_all_file_to_dir(dir_path: str, target_dir_path: str) -> bool:
        """
        :param dir_path: copy all file on dir
        :param target_dir_path: put file to target dir
        :return: True if success else False
        """

.. code-block:: python

    def rename_file(origin_file_path, target_name: str, file_extension=None) -> bool:
        """
        :param origin_file_path: which dir do we want to search file
        :param target_name: rename file to target name
        :param file_extension: Which extension do we search
        :return: True if success else False
        """

.. code-block:: python

    def remove_file(file_path: str) -> None:
        """
        :param file_path: which file do we want to remove
        :return: None
        """

.. code-block:: python

    def create_file(file_path: str, content: str) -> None:
        """
        :param file_path: create file on path
        :param content: what content will write to file
        :return: None
        """

.. code-block:: python

    def zip_dir(dir_we_want_to_zip: str, zip_name: str) -> None:
        """
        :param dir_we_want_to_zip: dir str path
        :param zip_name: zip file name
        :return: None
        """

.. code-block:: python

    def zip_file(zip_file_path: str, file: [str, List[str]]) -> None:
        """
        :param zip_file_path: add file to zip file
        :param file: single file path or list of file path (str) to add into zip
        :return: None
        """

.. code-block:: python

    def read_zip_file(zip_file_path: str, file_name: str, password: [str, None] = None) -> bytes:
        """
        :param zip_file_path: which zip do we want to read
        :param file_name: which file on zip do we want to read
        :param password: if zip have password use this password to unzip zip file
        :return:
        """

.. code-block:: python

    def unzip_file(
        zip_file_path: str, extract_member, extract_path: [str, None] = None, password: [str, None] = None) -> None:
        """
        :param zip_file_path: which zip we want to unzip
        :param extract_member: which member we want to unzip
        :param extract_path: extract member to path
        :param password: if zip have password use this password to unzip zip file
        :return: None
        """

.. code-block:: python

    def unzip_all(
        zip_file_path: str, extract_member: [str, None] = None,
        extract_path: [str, None] = None, password: [str, None] = None) -> None:
        """
        :param zip_file_path: which zip do we want to unzip
        :param extract_member: which member do we want to unzip
        :param extract_path: extract to path
        :param password: if zip have password use this password to unzip zip file
        :return: None
        """

.. code-block:: python

    def zip_info(zip_file_path: str) -> List[ZipInfo]:
        """
        :param zip_file_path: read zip file info
        :return: List[ZipInfo]
        """

.. code-block:: python

    def zip_file_info(zip_file_path: str) -> List[str]:
        """
        :param zip_file_path: read inside zip file info
        :return: List[str]
        """

.. code-block:: python

    def set_zip_password(zip_file_path: str, password: bytes) -> None:
        """
        :param zip_file_path: which zip do we want to set password
        :param password: password will be set
        :return: None
        """
