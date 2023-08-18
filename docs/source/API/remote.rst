Remote file api
----

.. code-block:: python

    def drive_delete_file(file_id: str) -> Union[Dict[str, str], None]:
        """
        :param file_id: Google Drive file id
        :return: Dict[str, str] or None
        """

.. code-block:: python

    def drive_add_folder(folder_name: str) -> Union[dict, None]:
        """
        :param folder_name: folder name will create on Google Drive
        :return: dict or None
        """

.. code-block:: python

    def drive_download_file(file_id: str, file_name: str) -> BytesIO:
        """
        :param file_id: file have this id will download
        :param file_name: file save on local name
        :return: file
        """

.. code-block:: python

    def drive_download_file_from_folder(folder_name: str) -> Union[dict, None]:
        """
        :param folder_name:  which folder do we want to download file
        :return: dict or None
        """

.. code-block:: python

    def drive_search_all_file() -> Union[dict, None]:
        """
        Search all file on Google Drive
        :return: dict or None
        """

.. code-block:: python

    def drive_search_file_mimetype(mime_type: str) -> Union[dict, None]:
        """
        :param mime_type: search all file with mime_type on Google Drive
        :return: dict or None
        """

.. code-block:: python

    def drive_search_field(field_pattern: str) -> Union[dict, None]:
        """
        :param field_pattern: what pattern will we use to search
        :return: dict or None
        """

.. code-block:: python

    def drive_share_file_to_user(
            file_id: str, user: str, user_role: str = "writer") -> Union[dict, None]:
        """
        :param file_id: which file do we want to share
        :param user: what user do we want to share
        :param user_role: what role do we want to share
        :return: dict or None
        """

.. code-block:: python

    def drive_share_file_to_anyone(file_id: str, share_role: str = "reader") -> Union[dict, None]:
        """
        :param file_id: which file do we want to share
        :param share_role: what role do we want to share
        :return: dict or None
        """

.. code-block:: python

    def drive_share_file_to_domain(
            file_id: str, domain: str, domain_role: str = "reader") -> Union[dict, None]:
        """
        :param file_id: which file do we want to share
        :param domain: what domain do we want to share
        :param domain_role: what role do we want to share
        :return: dict or None
        """

.. code-block:: python

    def drive_upload_to_drive(file_path: str, file_name: str = None) -> Union[dict, None]:
        """
        :param file_path: which file do we want to upload
        :param file_name: file name on Google Drive
        :return: dict or None
        """

.. code-block:: python

    def drive_upload_to_folder(folder_id: str, file_path: str, file_name: str = None) -> Union[dict, None]:
        """
        :param folder_id: which folder do we want to upload file into
        :param file_path: which file do we want to upload
        :param file_name: file name on Google Drive
        :return: dict or None
        """

.. code-block:: python

    def drive_upload_dir_to_drive(dir_path: str) -> List[Optional[set]]:
        """
        :param dir_path: which dir do we want to upload to drive
        :return: List[Optional[set]]
        """

.. code-block:: python

    def drive_upload_dir_to_folder(folder_id: str, dir_path: str) -> List[Optional[set]]:
        """
        :param folder_id: which folder do we want to put dir into
        :param dir_path: which dir do we want to upload
        :return: List[Optional[set]]
        """
