import { InboxOutlined } from '@ant-design/icons';
import { Alert, Button, Modal, Space, Typography, Upload, message } from 'antd';
import { useState } from 'react';
import type { ImportSource } from '../types/product';

const { Text } = Typography;

type Props = {
  open: boolean;
  onClose: () => void;
  onImport: (file: File) => Promise<void> | void;
};

const sources: Array<{
  key: ImportSource;
  title: string;
  subtitle: string;
  enabled: boolean;
}> = [
  { key: 'yunqi', title: '云启数据', subtitle: 'CSV / Excel', enabled: true },
  { key: 'temu', title: 'Temu 后台', subtitle: '后续支持', enabled: false },
  { key: '1688', title: '1688 数据', subtitle: '后续支持', enabled: false },
  { key: 'custom', title: '自定义 Excel', subtitle: '后续支持', enabled: false },
];

export function DataImportModal({ open, onClose, onImport }: Props) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);

  const handleImport = async () => {
    if (!selectedFile) {
      message.warning('请先选择云启文件');
      return;
    }
    setImporting(true);
    try {
      await onImport(selectedFile);
      setSelectedFile(null);
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
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="import" loading={importing} type="primary" onClick={handleImport}>
          开始导入
        </Button>,
      ]}
    >
      <Text type="secondary">选择数据来源并上传文件，系统会自动识别字段。</Text>

      <div className="source-grid">
        {sources.map((source) => (
          <button
            className={`source-card ${source.enabled ? 'source-card-active' : ''}`}
            disabled={!source.enabled}
            key={source.key}
            type="button"
          >
            <span className="source-title">{source.title}</span>
            <span className="source-subtitle">{source.subtitle}</span>
            {!source.enabled && <span className="source-badge">暂未开放</span>}
          </button>
        ))}
      </div>

      <Upload.Dragger
        accept=".csv,.xlsx"
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
        <p className="ant-upload-text">上传云启 CSV / Excel</p>
        <p className="ant-upload-hint">拖拽文件到这里，或点击选择文件</p>
      </Upload.Dragger>

      <Space direction="vertical" className="modal-note">
        <Alert
          message="导入后将在商品池中生成一个新批次，并回显商品记录。"
          showIcon
          type="warning"
        />
      </Space>
    </Modal>
  );
}
