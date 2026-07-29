/**
 * Inventory and purchasing — stock, products, bills, and payables.
 *
 * The stock view leads with valuation, because the number that must reconcile to
 * the Inventory ledger account is the one worth showing first.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Plus, ScanLine } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import type { Column } from '@/components/ui/DataTable';
import { DataTable, PageHeader, Pagination } from '@/components/ui/DataTable';
import { Input } from '@/components/ui/Input';
import { PartyFormModal } from '@/features/sales/PartyForm';
import {
  type Bill,
  type BillStatus,
  type MovementKind,
  type Product,
  type StockLevel,
  type Supplier,
  type StockMovement,
  inventoryApi,
} from '@/features/inventory/api';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatMoney, isNegativeMoney, isZeroMoney } from '@/lib/format';

type Tab = 'stock' | 'products' | 'suppliers' | 'movements' | 'bills' | 'payables';

const BILL_TONES: Record<BillStatus, BadgeTone> = {
  draft: 'neutral',
  posted: 'info',
  partially_paid: 'warning',
  paid: 'success',
  cancelled: 'danger',
};

const MOVEMENT_TONES: Partial<Record<MovementKind, BadgeTone>> = {
  receipt: 'success',
  issue: 'warning',
  adjustment: 'danger',
  transfer_in: 'info',
  transfer_out: 'info',
  reversal: 'danger',
};

export function InventoryPage() {
  const [tab, setTab] = useState<Tab>('stock');

  return (
    <div>
      <PageHeader
        title="Inventory & purchasing"
        description="Stock is an append-only ledger. Valuation is weighted average and reconciles exactly to the Inventory account."
      />

      <div className="border-border mb-4 flex gap-1 overflow-x-auto border-b" role="tablist">
        {(
          [
            ['stock', 'Stock'],
            ['products', 'Products'],
            ['suppliers', 'Suppliers'],
            ['movements', 'Movements'],
            ['bills', 'Bills'],
            ['payables', 'Payables'],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              'shrink-0 border-b-2 px-3 py-2 text-[13px] font-medium transition-colors',
              tab === key
                ? 'border-primary text-content'
                : 'text-content-muted hover:text-content border-transparent',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'stock' && <StockView />}
      {tab === 'products' && <ProductList />}
      {tab === 'suppliers' && <SupplierList />}
      {tab === 'movements' && <MovementLog />}
      {tab === 'bills' && <BillList />}
      {tab === 'payables' && <PayablesView />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stock
// ---------------------------------------------------------------------------
function StockView() {
  const { data: valuation } = useQuery({
    queryKey: ['stock-valuation'],
    queryFn: () => inventoryApi.valuation(),
  });
  const { data: levels, isLoading } = useQuery({
    queryKey: ['stock-levels'],
    queryFn: () => inventoryApi.levels(),
  });
  const { data: reorder } = useQuery({
    queryKey: ['reorder'],
    queryFn: () => inventoryApi.reorderReport(),
  });

  const columns: Column<StockLevel>[] = [
    {
      header: 'SKU',
      cell: (row) => <span className="font-mono text-[12px]">{row.product_sku}</span>,
    },
    { header: 'Product', cell: (row) => row.product_name },
    { header: 'Warehouse', hideOnMobile: true, cell: (row) => row.warehouse_code },
    { header: 'On hand', numeric: true, cell: (row) => formatMoney(row.quantity).replace('₹', '') },
    {
      header: 'Avg cost',
      numeric: true,
      hideOnMobile: true,
      cell: (row) => formatMoney(row.average_cost),
    },
    { header: 'Value', numeric: true, cell: (row) => formatMoney(row.total_value) },
  ];

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardBody>
            <p className="text-content-muted text-[11px] font-semibold tracking-wider uppercase">
              Stock value
            </p>
            <p className="text-content mt-1.5 text-[20px] font-semibold tabular-nums">
              {formatMoney(valuation?.total_value)}
            </p>
            <p className="text-content-muted mt-0.5 text-[11px]">
              Reconciles to the Inventory account
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <p className="text-content-muted text-[11px] font-semibold tracking-wider uppercase">
              Products in stock
            </p>
            <p className="text-content mt-1.5 text-[20px] font-semibold tabular-nums">
              {valuation?.product_count ?? 0}
            </p>
          </CardBody>
        </Card>
        <Card className={cn((reorder?.length ?? 0) > 0 && 'border-warning/40')}>
          <CardBody>
            <div className="flex items-center gap-2">
              {(reorder?.length ?? 0) > 0 && (
                <AlertTriangle className="text-warning h-3.5 w-3.5" aria-hidden />
              )}
              <p className="text-content-muted text-[11px] font-semibold tracking-wider uppercase">
                Need reorder
              </p>
            </div>
            <p className="text-content mt-1.5 text-[20px] font-semibold tabular-nums">
              {reorder?.length ?? 0}
            </p>
          </CardBody>
        </Card>
      </div>

      {reorder && reorder.length > 0 && (
        <Card className="border-warning/40">
          <CardHeader
            title="Below reorder level"
            description="At or under the level set on the product."
          />
          <DataTable
            columns={[
              {
                header: 'SKU',
                cell: (row) => <span className="font-mono text-[12px]">{row.sku}</span>,
              },
              { header: 'Product', cell: (row) => row.name },
              {
                header: 'On hand',
                numeric: true,
                cell: (row) => formatMoney(row.quantity_on_hand).replace('₹', ''),
              },
              {
                header: 'Reorder at',
                numeric: true,
                cell: (row) => formatMoney(row.reorder_level).replace('₹', ''),
              },
              {
                header: 'Short by',
                numeric: true,
                cell: (row) => (
                  <span className="text-warning font-medium">
                    {formatMoney(row.shortfall).replace('₹', '')}
                  </span>
                ),
              },
            ]}
            rows={reorder}
            rowKey={(row) => row.product_id}
          />
        </Card>
      )}

      <Card>
        <CardHeader title="Stock on hand" />
        <DataTable
          columns={columns}
          rows={levels ?? []}
          rowKey={(row) => `${row.product_id}-${row.warehouse_id}`}
          isLoading={isLoading}
          empty={{
            title: 'No stock yet',
            description: 'Record a goods receipt to bring stock in.',
          }}
        />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Products
// ---------------------------------------------------------------------------
function ProductList() {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [scan, setScan] = useState('');
  const [creating, setCreating] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['products', page, query],
    queryFn: () => inventoryApi.products({ page, page_size: 25, q: query || undefined }),
  });

  const lookup = useMutation({
    mutationFn: (barcode: string) => inventoryApi.byBarcode(barcode),
    onSuccess: (product) => {
      toast.success(product.name, { description: `SKU ${product.sku}` });
      setScan('');
    },
    onError: () => toast.error('No product with that barcode'),
  });

  const columns: Column<Product>[] = [
    {
      header: 'SKU',
      cell: (row) => <span className="font-mono text-[12px]">{row.sku}</span>,
    },
    {
      header: 'Product',
      cell: (row) => (
        <div>
          <p className="text-content">{row.name}</p>
          {row.barcode && <p className="text-content-muted font-mono text-[11px]">{row.barcode}</p>}
        </div>
      ),
    },
    {
      header: 'Kind',
      hideOnMobile: true,
      cell: (row) => <Badge tone={row.kind === 'stocked' ? 'info' : 'neutral'}>{row.kind}</Badge>,
    },
    {
      header: 'GST',
      numeric: true,
      hideOnMobile: true,
      cell: (row) => `${Number(row.tax_rate)}%`,
    },
    { header: 'Sale price', numeric: true, cell: (row) => formatMoney(row.sale_price) },
    {
      header: 'On hand',
      numeric: true,
      cell: (row) =>
        row.tracks_stock ? (
          <span className={cn(row.needs_reorder && 'text-warning font-medium')}>
            {formatMoney(row.quantity_on_hand).replace('₹', '')}
          </span>
        ) : (
          <span className="text-content-muted">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-4">
      {creating && <ProductComposer onClose={() => setCreating(false)} />}

      <Card>
        <CardHeader
          title="Products"
          action={
            <div className="flex flex-wrap items-end gap-2">
              <Input
                placeholder="Scan barcode…"
                leftIcon={<ScanLine />}
                value={scan}
                onChange={(event) => setScan(event.target.value)}
                onKeyDown={(event) => {
                  // A hardware scanner types the code then sends Enter.
                  if (event.key === 'Enter' && scan.trim()) lookup.mutate(scan.trim());
                }}
                className="w-44"
              />
              <Input
                placeholder="Search…"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                className="w-40"
              />
              <Button size="sm" leftIcon={<Plus />} onClick={() => setCreating(true)}>
                New
              </Button>
            </div>
          }
        />
        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ title: 'No products', description: 'Add one to start buying and selling.' }}
        />
        {data && (
          <Pagination
            page={data.meta.page}
            totalPages={data.meta.total_pages}
            totalItems={data.meta.total_items}
            onChange={setPage}
          />
        )}
      </Card>
    </div>
  );
}

function ProductComposer({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: '',
    sku: '',
    barcode: '',
    unit: 'NOS',
    tax_rate: '18',
    sale_price: '',
    purchase_price: '',
    reorder_level: '',
  });

  const create = useMutation({
    mutationFn: () =>
      inventoryApi.createProduct({
        name: form.name,
        sku: form.sku || undefined,
        barcode: form.barcode || undefined,
        unit: form.unit,
        tax_rate: form.tax_rate || '0',
        sale_price: form.sale_price || '0',
        purchase_price: form.purchase_price || '0',
        reorder_level: form.reorder_level || '0',
      }),
    onSuccess: (product) => {
      toast.success(`${product.sku} created`);
      void queryClient.invalidateQueries({ queryKey: ['products'] });
      onClose();
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not create the product'),
  });

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  return (
    <Card>
      <CardHeader title="New product" description="SKU is generated if left blank." />
      <CardBody className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Name" value={form.name} onChange={set('name')} autoFocus />
          <Input label="SKU" placeholder="auto" value={form.sku} onChange={set('sku')} />
          <Input
            label="Barcode"
            placeholder="EAN / UPC"
            value={form.barcode}
            onChange={set('barcode')}
          />
          <Input label="Unit" value={form.unit} onChange={set('unit')} />
          <Input
            label="GST %"
            inputMode="decimal"
            value={form.tax_rate}
            onChange={set('tax_rate')}
          />
          <Input
            label="Reorder level"
            inputMode="decimal"
            value={form.reorder_level}
            onChange={set('reorder_level')}
          />
          <Input
            label="Purchase price"
            inputMode="decimal"
            value={form.purchase_price}
            onChange={set('purchase_price')}
          />
          <Input
            label="Sale price"
            inputMode="decimal"
            value={form.sale_price}
            onChange={set('sale_price')}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={form.name.trim() === ''}
            loading={create.isPending}
            onClick={() => create.mutate()}
          >
            Create product
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Movements
// ---------------------------------------------------------------------------
function MovementLog() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery({
    queryKey: ['stock-movements', page],
    queryFn: () => inventoryApi.movements({ page, page_size: 25 }),
  });

  const columns: Column<StockMovement>[] = [
    { header: 'Date', cell: (row) => formatDate(row.movement_date) },
    { header: 'Product', cell: (row) => row.product_name },
    {
      header: 'Type',
      cell: (row) => (
        <Badge tone={MOVEMENT_TONES[row.kind] ?? 'neutral'}>{row.kind.replace('_', ' ')}</Badge>
      ),
    },
    {
      header: 'Qty',
      numeric: true,
      cell: (row) => (
        <span className={cn(isNegativeMoney(row.quantity) ? 'text-warning' : 'text-success')}>
          {isNegativeMoney(row.quantity) ? '' : '+'}
          {formatMoney(row.quantity).replace('₹', '')}
        </span>
      ),
    },
    {
      header: 'Balance',
      numeric: true,
      hideOnMobile: true,
      cell: (row) => formatMoney(row.balance_after).replace('₹', ''),
    },
    { header: 'Cost', numeric: true, cell: (row) => formatMoney(row.total_cost) },
    {
      header: 'Posted',
      hideOnMobile: true,
      cell: (row) =>
        row.journal_entry_id ? (
          <Badge tone="success">yes</Badge>
        ) : (
          // A transfer moves no value, so it correctly posts nothing.
          <span className="text-content-muted text-[11px]">no ledger effect</span>
        ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Stock movements"
        description="Append-only. Every receipt, issue, adjustment, and transfer."
      />
      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        rowKey={(row) => row.id}
        isLoading={isLoading}
        empty={{ title: 'No movements', description: 'Stock activity appears here.' }}
      />
      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          totalItems={data.meta.total_items}
          onChange={setPage}
        />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Suppliers
// ---------------------------------------------------------------------------
/**
 * Suppliers had no screen at all until now, which made two workflows unreachable:
 * entering a bill, and confirming a scanned invoice — both need a supplier on file
 * and neither offered a way to create one.
 */
function SupplierList() {
  const [adding, setAdding] = useState(false);
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery({
    queryKey: ['suppliers', page],
    queryFn: () => inventoryApi.suppliers({ page, page_size: 25 }),
  });

  const columns: Column<Supplier>[] = [
    { header: 'Code', cell: (row) => <span className="font-mono text-[12px]">{row.code}</span> },
    {
      header: 'Supplier',
      cell: (row) => (
        <div>
          <p className="text-content">{row.name}</p>
          {row.email && <p className="text-content-muted text-[11px]">{row.email}</p>}
        </div>
      ),
    },
    {
      header: 'GSTIN',
      hideOnMobile: true,
      cell: (row) =>
        row.gstin ? (
          <span className="font-mono text-[11px]">{row.gstin}</span>
        ) : (
          <span className="text-content-muted">—</span>
        ),
    },
    { header: 'City', hideOnMobile: true, cell: (row) => row.city ?? '—' },
    { header: 'Terms', numeric: true, cell: (row) => `${row.payment_terms_days} days` },
  ];

  return (
    <Card>
      <CardHeader
        title="Suppliers"
        description="A supplier's GSTIN is what lets input GST be claimed and what matches a scanned invoice automatically."
        action={
          <Button onClick={() => setAdding(true)}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            New supplier
          </Button>
        }
      />
      <PartyFormModal kind="supplier" open={adding} onClose={() => setAdding(false)} />
      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        rowKey={(row) => row.id}
        isLoading={isLoading}
        empty={{
          title: 'No suppliers',
          description: 'Add one to enter bills or to confirm a scanned invoice.',
          action: (
            <Button onClick={() => setAdding(true)}>
              <Plus className="h-3.5 w-3.5" aria-hidden />
              Add a supplier
            </Button>
          ),
        }}
      />
      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          totalItems={data.meta.total_items}
          onChange={setPage}
        />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Bills
// ---------------------------------------------------------------------------
function BillList() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery({
    queryKey: ['bills', page],
    queryFn: () => inventoryApi.bills({ page, page_size: 25 }),
  });

  const post = useMutation({
    mutationFn: (id: string) => inventoryApi.postBill(id),
    onSuccess: (bill) => {
      toast.success(`${bill.bill_number} posted`, {
        description: 'Payable recognised and input GST claimed.',
      });
      void queryClient.invalidateQueries({ queryKey: ['bills'] });
      void queryClient.invalidateQueries({ queryKey: ['trial-balance'] });
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not post the bill'),
  });

  const columns: Column<Bill>[] = [
    {
      header: 'Bill',
      cell: (row) => (
        <div>
          <p className="font-mono text-[12px]">{row.bill_number}</p>
          {row.supplier_invoice_number && (
            <p className="text-content-muted text-[11px]">
              their ref {row.supplier_invoice_number}
            </p>
          )}
        </div>
      ),
    },
    { header: 'Supplier', cell: (row) => row.supplier_name },
    {
      header: 'Due',
      hideOnMobile: true,
      cell: (row) => (
        <span className={cn(row.is_overdue && 'text-danger font-medium')}>
          {formatDate(row.due_date)}
        </span>
      ),
    },
    {
      header: 'Status',
      cell: (row) => <Badge tone={BILL_TONES[row.status]}>{row.status.replace('_', ' ')}</Badge>,
    },
    { header: 'Total', numeric: true, cell: (row) => formatMoney(row.grand_total) },
    {
      header: 'Outstanding',
      numeric: true,
      cell: (row) =>
        isZeroMoney(row.outstanding) ? (
          <span className="text-content-muted">—</span>
        ) : (
          formatMoney(row.outstanding)
        ),
    },
    {
      header: '',
      cell: (row) =>
        row.status === 'draft' ? (
          <Button
            size="sm"
            variant="secondary"
            loading={post.isPending && post.variables === row.id}
            onClick={() => post.mutate(row.id)}
          >
            Post
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Bills"
        description="A duplicate supplier invoice number is refused — it is the most expensive error in payables."
      />
      <DataTable
        columns={columns}
        rows={data?.items ?? []}
        rowKey={(row) => row.id}
        isLoading={isLoading}
        empty={{
          title: 'No bills',
          description: 'Enter a supplier invoice to record what you owe.',
        }}
      />
      {data && (
        <Pagination
          page={data.meta.page}
          totalPages={data.meta.total_pages}
          totalItems={data.meta.total_items}
          onChange={setPage}
        />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Payables
// ---------------------------------------------------------------------------
function PayablesView() {
  const { data, isLoading } = useQuery({
    queryKey: ['payables-ageing'],
    queryFn: () => inventoryApi.payablesAgeing(),
  });

  if (isLoading || !data) {
    return (
      <Card>
        <DataTable columns={[]} rows={[]} rowKey={() => ''} isLoading />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardBody>
            <p className="text-content-muted text-[11px] font-semibold tracking-wider uppercase">
              Total payable
            </p>
            <p className="text-content mt-1.5 text-[20px] font-semibold tabular-nums">
              {formatMoney(data.total_outstanding)}
            </p>
          </CardBody>
        </Card>
        <Card className={cn(!isZeroMoney(data.total_overdue) && 'border-danger/40')}>
          <CardBody>
            <p className="text-content-muted text-[11px] font-semibold tracking-wider uppercase">
              Overdue
            </p>
            <p className="text-content mt-1.5 text-[20px] font-semibold tabular-nums">
              {formatMoney(data.total_overdue)}
            </p>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Payables ageing" description={`As at ${formatDate(data.as_of)}`} />
        <DataTable
          columns={[
            { header: 'Bucket', cell: (row) => row.label },
            { header: 'Bills', numeric: true, cell: (row) => String(row.bill_count) },
            { header: 'Amount', numeric: true, cell: (row) => formatMoney(row.amount) },
          ]}
          rows={data.buckets}
          rowKey={(row) => row.label}
          empty={{ title: 'Nothing payable', description: 'No unpaid bills.' }}
        />
      </Card>
    </div>
  );
}
