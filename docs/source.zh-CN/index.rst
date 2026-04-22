automation_file
===============

语言：`English <../html/index.html>`_ | `繁體中文 <../html-zh-TW/index.html>`_ | **简体中文**

以自动化为核心的 Python 库，涵盖本地文件 / 目录 / zip 操作、HTTP 下载
以及远程存储（Google Drive、S3、Azure Blob、Dropbox、SFTP）。内置 PySide6 图形界面，
把每一项功能以标签页的形式呈现。所有动作以 JSON 描述，统一通过
:class:`~automation_file.core.action_registry.ActionRegistry` 调度。

快速开始
--------

从 PyPI 安装并执行 JSON 动作列表：

.. code-block:: bash

   pip install automation_file
   python -m automation_file --execute_file my_actions.json

或直接通过 Python 代码调用：

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
   ])

.. toctree::
   :maxdepth: 2
   :caption: 目录

   architecture
   usage
   api/index

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
