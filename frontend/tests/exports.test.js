import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ExportsPanel } from '../src/components/exports_panel.js';
import { api } from '../src/services/api.js';

vi.mock('../src/services/api.js', async () => {
  const actual = await vi.importActual('../src/services/api.js');
  return {
    api: {
      ...actual.api,
      createExport: vi.fn(),
      getExport: vi.fn(),
      downloadExport: vi.fn(),
    }
  };
});

describe('ExportsPanel PDF calligraphié §A.2 / §17.1', () => {
  let container;
  const projectId = 'proj-export-test';

  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'test-exports';
    document.body.appendChild(container);
    vi.clearAllMocks();
    api.createExport.mockResolvedValue({ id: 'exp-123', project_id: projectId, format: 'pdf', status: 'pending' });
    api.getExport.mockResolvedValue({ id: 'exp-123', project_id: projectId, format: 'pdf', status: 'completed', file_path: '/tmp/test.pdf' });
    api.downloadExport.mockResolvedValue(new Blob(['%PDF-1.4 fake'], { type: 'application/pdf' }));
  });

  afterEach(() => {
    container.remove();
  });

  it('affiche le panneau avec bouton Export PDF', async () => {
    const panel = new ExportsPanel('test-exports', projectId);
    panel.mount();
    expect(container.textContent).toContain('Exports');
    expect(container.textContent).toContain('PDF');
    expect(container.querySelector('[data-testid="export-pdf-btn"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="export-srt-btn"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="export-vtt-btn"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="export-quality-btn"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="export-status"]')).not.toBeNull();
  });

  it('crée un export PDF et poll le statut jusqu\'à completed', async () => {
    const panel = new ExportsPanel('test-exports', projectId);
    panel.mount();
    const btn = container.querySelector('[data-testid="export-pdf-btn"]');
    btn.click();
    await new Promise(r => setTimeout(r, 0));
    expect(api.createExport).toHaveBeenCalledWith(projectId, 'pdf');
    // Après création, le panel doit poller
    await new Promise(r => setTimeout(r, 600)); // poll 500ms
    expect(api.getExport).toHaveBeenCalled();
    // Le statut doit être affiché
    expect(container.querySelector('[data-testid="export-status"]').textContent).toContain('completed');
  });

  it('affiche le lien de téléchargement quand completed', async () => {
    api.getExport.mockResolvedValue({ id: 'exp-123', project_id: projectId, format: 'pdf', status: 'completed', file_path: '/tmp/test.pdf' });
    const panel = new ExportsPanel('test-exports', projectId);
    panel.mount();
    // Simuler un export déjà terminé
    panel.lastExportId = 'exp-123';
    await panel.checkStatus();
    await new Promise(r => setTimeout(r, 0));
    const dl = container.querySelector('[data-testid="export-download"]');
    expect(dl.textContent).toContain('Télécharger');
    expect(container.querySelector('[data-testid="download-link"]')).not.toBeNull();
  });

  it('gère l\'erreur de génération', async () => {
    api.createExport.mockRejectedValueOnce(new Error('Network error'));
    const panel = new ExportsPanel('test-exports', projectId);
    panel.mount();
    const btn = container.querySelector('[data-testid="export-pdf-btn"]');
    btn.click();
    await new Promise(r => setTimeout(r, 0));
    expect(container.querySelector('[data-testid="export-status"]').getAttribute('data-status')).toBe('error');
  });

  it('expose le web component rythmo-exports', () => {
    expect(customElements.get('rythmo-exports')).toBeDefined();
  });

  it('crée un export rapport qualité et poll le statut', async () => {
    const panel = new ExportsPanel('test-exports', projectId);
    panel.mount();
    const btn = container.querySelector('[data-testid="export-quality-btn"]');
    expect(btn).not.toBeNull();
    btn.click();
    await new Promise(r => setTimeout(r, 0));
    expect(api.createExport).toHaveBeenCalledWith(projectId, 'quality_report');
    await new Promise(r => setTimeout(r, 600));
    expect(api.getExport).toHaveBeenCalled();
  });
});
