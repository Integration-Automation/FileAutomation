automation_file
===============

語言：`English <../html/index.html>`_ | **繁體中文** | `简体中文 <../html-zh-CN/index.html>`_

以自動化為核心的 Python 函式庫，涵蓋本地檔案 / 目錄 / zip 操作、HTTP 下載
與遠端儲存（Google Drive、S3、Azure Blob、Dropbox、SFTP）。內建 PySide6 圖形介面，
把每一項功能以分頁形式呈現。所有動作以 JSON 描述，統一透過
:class:`~automation_file.core.action_registry.ActionRegistry` 調度。

快速開始
--------

從 PyPI 安裝並執行 JSON 動作清單：

.. code-block:: bash

   pip install automation_file
   python -m automation_file --execute_file my_actions.json

或直接從 Python 程式碼呼叫：

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
   ])

.. toctree::
   :maxdepth: 2
   :caption: 目錄

   architecture
   usage
   api/index

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
