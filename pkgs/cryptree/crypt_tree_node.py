from pydantic import Field
from typing import Optional, Type
import json
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from model import Metadata, ChildNodeInfo, CryptreeNodeModel
import base64
from ipfs_client import IpfsClient
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import os
from root_id_store_contract import RootIdStoreContract

class CryptreeNode(CryptreeNodeModel):
    metadata: Metadata = Field(..., alias="metadata")
    subfolder_key: str = Field(..., alias="subfolder_key")
    cid: str = Field(..., alias="cid")

    @property
    def is_leaf(self) -> bool:
        return len(self.metadata.children) == 0

    @property
    def is_file(self) -> bool:
        return len(self.metadata.children) == 1 and self.metadata.children[0].fk is not None

    # ノードを作成する
    @classmethod
    def create_node(cls, name: str, owner_id: str, isDirectory: bool, ipfs_client: Type[IpfsClient], root_key: str,  parent: Optional['CryptreeNode'] = None, file_data: Optional[bytes] = None) -> 'CryptreeNode':
        # キー生成
        if parent is None:
            decoded_key = base64.b64decode(root_key)
            salt = os.urandom(16)

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend()
            )
            subfolder_key = base64.urlsafe_b64encode(kdf.derive(decoded_key)).decode()
        else:
            subfolder_key = Fernet.generate_key().decode()
        file_key = Fernet.generate_key().decode() if not isDirectory else None

        # メタデータの作成
        metadata = Metadata(
            name=name,
            owner_id=owner_id,
            created_at=datetime.now(timezone.utc),
            children=[]
        )

        if not isDirectory:
            # ファイルの場合、ファイルデータを暗号化
            enc_file_data = CryptreeNode.encrypt(file_key, file_data)
            cid = ipfs_client.add_bytes(enc_file_data)
            file_info = ChildNodeInfo(cid=cid, fk=file_key)
            metadata.children.append(file_info)

        # メタデータを暗号化してIPFSにアップロード
        enc_metadata = CryptreeNode.encrypt(subfolder_key, metadata.model_dump_json().encode())
        cid = ipfs_client.add_bytes(enc_metadata)

        if cid is None:
            raise ValueError("Failed to upload metadata to IPFS.")

        # # ルートノードの新規作成かどうかを判定
        if parent is None:
            RootIdStoreContract.update_root_id(owner_id, cid)
        else:
            child_info = ChildNodeInfo(cid=cid, sk=subfolder_key)
            parent.metadata.children.append(child_info)
            parent_enc_metadata = parent.encrypt_metadata()
            parent_new_cid = ipfs_client.add_bytes(parent_enc_metadata)
            root_id = RootIdStoreContract.get_root_id(owner_id)
            # 親ノードおよびルートノードまでの先祖ノード全てのメタデータを更新
            CryptreeNode.update_all_nodes(parent.metadata.owner_id, parent_new_cid, parent.subfolder_key, ipfs_client, root_key)
            new_root_id = root_id
            # ルートIDが変更されるまでループ
            while root_id == new_root_id:
                new_root_id = RootIdStoreContract.get_root_id(owner_id)

        # インスタンスの作成と返却
        return cls(
            metadata=metadata,
            subfolder_key=subfolder_key,
            cid=cid,
        )

    def delete(
        self,
        node_id: str,
        ipfs_client: Type[IpfsClient],
        root_key: str,
    ) -> 'CryptreeNode':
        # Check if the parent is provided
        if self is None:
            raise ValueError("Parent node must be provided.")
        # Remove this node from the parent's child list
        self.metadata.children = [child for child in self.metadata.children if child.cid != node_id]
        # Encrypt and upload the updated parent metadata to IPFS
        enc_metadata = CryptreeNode.encrypt(self.subfolder_key, self.metadata.model_dump_json().encode())
        self.cid = ipfs_client.add_bytes(enc_metadata)
        # Reflect the parent's update to all nodes
        CryptreeNode.update_all_nodes(
            address=self.metadata.owner_id,
            new_cid=self.cid,
            target_subfolder_key=self.subfolder_key,
            ipfs_client=ipfs_client,
            root_key=root_key
        )

        return self


    def encrypt_metadata(self) -> bytes:
        return CryptreeNode.encrypt(self.subfolder_key, self.metadata.model_dump_json().encode())
    
    @classmethod
    def update_all_nodes(cls, address: str, new_cid: str, target_subfolder_key: str, ipfs_client: Type[IpfsClient], root_key: str):
        # ルートノードのから下の階層に降りながら、該当のサブフォルダキーを持つノードを探し、新しいCIDに更新する
        
        root_id = RootIdStoreContract.get_root_id(address)
        root_node = cls.get_node(root_id, root_key, ipfs_client)

        # ルートIDの更新
        def update_root_callback(address, new_root_id):
            RootIdStoreContract.update_root_id(address, new_root_id)

        # ルートIDとターゲットのサブフォルダキーが一致する場合、ルートノードのCIDを更新
        if root_node.subfolder_key == target_subfolder_key:
            update_root_callback(address, new_cid)
        else:
            cls.update_node(root_node, address, target_subfolder_key, new_cid, ipfs_client, root_key, update_root_callback)

    @classmethod
    def update_node(cls, node: 'CryptreeNode', address: str, target_subfolder_key: str, new_cid: str, ipfs_client: Type[IpfsClient], root_key: str, callback):
        children = node.metadata.children
        for index, child in enumerate(children):
            # fileだった場合はスキップ
            if child.sk is None:
                continue
            child_subfolder_key = child.sk
            # サブフォルダキーが一致する場合、CIDを更新
            if child_subfolder_key == target_subfolder_key:
                node.metadata.children[index].cid = new_cid
                enc_metadata = node.encrypt_metadata()
                new_cid = ipfs_client.add_bytes(enc_metadata)
                # ここがupdate_root_id or update_all_nodesになる
                callback(address, new_cid)
                break
            else:
                # サブフォルダキーが一致しない場合、さらに子ノードを探索
                child_node = cls.get_node(child.cid, child_subfolder_key, ipfs_client)
                if not child_node.is_leaf:
                    def update_all_again_callback(address, new_cid):
                        cls.update_all_nodes(address, new_cid, node.subfolder_key, ipfs_client, root_key)
                    cls.update_node(child_node, address, target_subfolder_key, new_cid, ipfs_client, root_key, update_all_again_callback)

    @classmethod
    def get_node(cls, cid: str, sk: str, ipfs_client: Type[IpfsClient]) -> 'CryptreeNode':
        enc_metadata = ipfs_client.cat(cid)
        metadata_bytes = CryptreeNode.decrypt(sk, enc_metadata)
        metadata = json.loads(metadata_bytes)
        return cls(metadata=metadata, subfolder_key=sk, cid=cid)

    @staticmethod
    def encrypt(key: str, data: bytes) -> bytes:
        return Fernet(key).encrypt(data)

    @staticmethod
    def decrypt(key: str, data: bytes) -> bytes:
        return Fernet(key).decrypt(data)

    def re_encrypt_and_update(self, parent_node: 'CryptreeNode', ipfs_client: Type[IpfsClient], root_key: str) -> 'CryptreeNode':
        # 指定したノードの更新前のsubfolder_keyを保持
        old_subfolder_key = self.subfolder_key

        # 指定したノードから最下層のノードに向かって再帰的に再暗号化を行う
        self = self.re_encrypt(ipfs_client)

        # 指定したノードの親ノードのメタデータを更新
        for child in parent_node.metadata.children:
            if child.sk == old_subfolder_key:
                child.cid = self.cid
                child.sk = self.subfolder_key
                break
        enc_parent_metadata = parent_node.encrypt_metadata()
        new_parent_cid = ipfs_client.add_bytes(enc_parent_metadata)

        # 親ノードおよびルートノードまでの先祖ノード全てのメタデータを更新
        CryptreeNode.update_all_nodes(parent_node.metadata.owner_id, new_parent_cid, parent_node.subfolder_key, ipfs_client, root_key)

        return self

    def re_encrypt(self, ipfs_client: Type[IpfsClient]) -> 'CryptreeNode':
        if self.is_leaf:
            self.subfolder_key = Fernet.generate_key().decode()
            enc_metadata = self.encrypt_metadata()
            self.cid = ipfs_client.add_bytes(enc_metadata)
            return self

        children = self.metadata.children

        if self.is_file:
            file_info = children[0]
            file_data = CryptreeNode.decrypt(file_info.fk, ipfs_client.cat(file_info.cid))
            file_info.fk = Fernet.generate_key().decode()
            enc_file_data = CryptreeNode.encrypt(file_info.fk, file_data)
            file_info.cid = ipfs_client.add_bytes(enc_file_data)
            self.subfolder_key = Fernet.generate_key().decode()
            enc_metadata = self.encrypt_metadata()
            self.cid = ipfs_client.add_bytes(enc_metadata)
            return self

        for child_info in children:
            child_node = CryptreeNode.get_node(child_info.cid, child_info.sk, ipfs_client)
            new_child_node = child_node.re_encrypt(ipfs_client)
            child_info.cid = new_child_node.cid
            child_info.sk = new_child_node.subfolder_key

        self.subfolder_key = Fernet.generate_key().decode()
        enc_metadata = self.encrypt_metadata()
        self.cid = ipfs_client.add_bytes(enc_metadata)
        return self
