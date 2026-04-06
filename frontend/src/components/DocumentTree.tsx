import { useEffect, useState } from 'react';
import { api } from '../services/api';
import type { Document, DocumentNode } from '../types/api';

export function DocumentTree({ documentId }: { documentId: string }) {
  const [nodes, setNodes] = useState<DocumentNode[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getDocumentNodes(documentId)
      .then(setNodes)
      .finally(() => setLoading(false));
  }, [documentId]);

  if (loading) return <div className="p-4">Loading nodes...</div>;
  if (!nodes.length) return <div className="p-4 text-gray-500">No nodes extracted yet. Has it been parsed?</div>;

  return (
    <div className="document-tree mt-6 border border-[color:var(--color-border)] rounded-[var(--radius-lg)] p-4 bg-[color:var(--color-bg-secondary)]">
      <h3 className="text-lg font-bold mb-4">Document Nodes Tree</h3>
      <div className="flex flex-col gap-3">
        {nodes.map(node => (
          <div key={node.id} className="node-card p-3 bg-[color:var(--color-bg-primary)] rounded-[var(--radius-md)] border border-[color:var(--color-border)] hover:border-blue-500 transition-colors">
            <div className="flex justify-between items-center mb-2">
              <span className={`badge ${node.node_type === 'heading' ? 'badge--accent' : 'badge--outline'}`}>
                {node.node_type}
              </span>
              <span className="text-xs text-gray-400">Order: {node.order_index}</span>
            </div>
            <p className="text-sm text-[color:var(--color-text-primary)] whitespace-pre-wrap font-mono">
              {node.normalized_text || node.raw_text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
