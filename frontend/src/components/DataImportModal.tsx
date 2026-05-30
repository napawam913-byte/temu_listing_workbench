import { InboxOutlined } from '@ant-design/icons';
import { Alert, Button, Input, Modal, Space, Typography, Upload, message } from 'antd';
import { useState } from 'react';
import type { ImportSource } from '../types/product';

const { Text } = Typography;
const { TextArea } = Input;

type Props = {
  open: boolean;
  onClose: () => void;
  onImport: (file: File) => Promise<void> | void;
  onImport1688Links: (productUrls: string[]) => Promise<void> | void;
};

const sources: Array<{
  key: ImportSource;
  title: string;
  subtitle: string;
  enabled: boolean;
}> = [
  { key: 'yunqi', title: '云启数据', subtitle: 'CSV / Excel', enabled: true },
  { key: 'temu', title: 'Temu 后台', subtitle: '后续支持', enabled: false },
  { key: '1688', title: '1688 数据', subtitle: '商品链接采集', enabled: true },
  { key: 'custom', title: '自定义 Excel', subtitle: '后续支持', enabled: false },
];

export function DataImportModal({ open, onClose, onImport, onImport1688Links }: Props) {
  const [selectedSource, setSelectedSource] = useState<ImportSource>('yunqi');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [linkText, setLinkText] = useState('');
  const [importing, setImporting] = useState(false);

  const resetImportState = () => {
    setSelectedFile(null);
    setLinkText('');
    setSelectedSource('yunqi');
  };

  const handleClose = () => {
    if (!importing) {
      resetImportState();
      onClose();
    }
  };

  const handleImport = async () => {
    const productUrls = linkText
      .split(/[\n,，\s]+/)
      .map((url) => url.trim())
      .filter(Boolean);

    if (selectedSource === 'yunqi' && !selectedFile) {
      message.warning('请先选择云启文件');
      return;
    }
    if (selectedSource === '1688' && productUrls.length === 0) {
      message.warning('请先填写 1688 商品链接');
      return;
    }

    setImporting(true);
    try {
      if (selectedSource === '1688') {
        await onImport1688Links(productUrls);
      } else if (selectedFile) {
        await onImport(selectedFile);
      }
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
      <Text type="secondary">选择数据来源并上传文件，系统会自动识别字段。</Text>

      <div className="source-grid">
        {sources.map((source) => (
          <button
            className={`source-card ${source.enabled ? 'source-card-enabled' : ''} ${
              source.key === selectedSource ? 'source-card-active' : ''
            }`}
            disabled={!source.enabled}
            key={source.key}
            type="button"
            onClick={() => {
              if (source.enabled) setSelectedSource(source.key);
            }}
          >
            <span className="source-title">{source.title}</span>
            <span className="source-subtitle">{source.subtitle}</span>
            {!source.enabled && <span className="source-badge">暂未开放</span>}
          </button>
        ))}
      </div>

      {selectedSource === 'yunqi' ? (
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
      ) : (
        <div className="link-import-panel">
          <Text strong>1688 商品链接</Text>
          <TextArea
            allowClear
            autoSize={{ minRows: 5, maxRows: 8 }}
            placeholder={'粘贴 1688 商品详情链接，多个链接可换行填写\n例如：https://detail.1688.com/offer/123456.html'}
            value={linkText}
            onChange={(event) => setLinkText(event.target.value)}
          />
          <Text type="secondary">系统会采集商品标题、主图、价格和原始链接，并作为 1688 商品加入商品列表。</Text>
        </div>
      )}

      <Space direction="vertical" className="modal-note">
        <Alert
          message={
            selectedSource === '1688'
              ? '链接采集成功后会生成 1688 商品记录，可在商品列表中查看并访问原页。'
              : '导入后将在商品池中生成一个新批次，并回显商品记录。'
          }
          showIcon
          type="warning"
        />
      </Space>
    </Modal>
  );
}
