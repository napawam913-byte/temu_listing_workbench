import { InboxOutlined } from '@ant-design/icons';
import { Alert, Button, Modal, Space, Typography, Upload, message } from 'antd';
import { useState } from 'react';

const { Text } = Typography;

type Props = {
  open: boolean;
  onClose: () => void;
  onImport: (file: File) => Promise<void> | void;
};

export function DataImportModal({ open, onClose, onImport }: Props) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);

  const resetImportState = () => {
    setSelectedFile(null);
  };

  const handleClose = () => {
    if (!importing) {
      resetImportState();
      onClose();
    }
  };

  const handleImport = async () => {
    if (!selectedFile) {
      message.warning('请先选择店小秘标准 Excel');
      return;
    }

    setImporting(true);
    try {
      await onImport(selectedFile);
      resetImportState();
    } finally {
      setImporting(false);
    }
  };

  return (
    <Modal
      title="数据导入"
      open={open}
      width={560}
      centered
      onCancel={handleClose}
      footer={[
        <Button key="cancel" onClick={handleClose}>
          取消
        </Button>,
        <Button key="import" loading={importing} type="primary" onClick={handleImport}>
          开始导入
        </Button>,
      ]}
    >
      <Text type="secondary">仅支持店小秘标准 Excel 模板，格式与当前导出的店小秘模板一致。</Text>

      <div style={{ marginTop: 20 }}>
        <Upload.Dragger
          accept=".xlsx,.xlsm"
          beforeUpload={(file) => {
            setSelectedFile(file);
            message.success(`已选择文件：${file.name}`);
            return false;
          }}
          onRemove={() => setSelectedFile(null)}
          maxCount={1}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">上传店小秘标准 Excel</p>
          <p className="ant-upload-hint">拖拽文件到这里，或点击选择文件</p>
        </Upload.Dragger>
      </div>

      <Space direction="vertical" className="modal-note">
        <Alert
          message="导入后只会写入商品池，并同步生成链接列表 SKU 回显数据。"
          showIcon
          type="warning"
        />
      </Space>
    </Modal>
  );
}
