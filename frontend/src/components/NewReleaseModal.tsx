import { useEffect, useState, type FormEvent } from 'react';
import type { NewReleaseForm, QaValidationChoice } from '../types/release';
import { QA_SIGNOFF_ALLOWED_EXTENSIONS } from '../types/release';

interface NewReleaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (form: NewReleaseForm) => void | Promise<void>;
  submitting?: boolean;
  submitError?: string | null;
}

const emptyForm: NewReleaseForm = {
  releaseBranch: '',
  pr: '',
  jira: '',
  qaSignOff: 'PrTests',
  qaReason: '',
  qaSignOffAttachment: null,
  environment: '',
  releaseDate: '',
};

const ACCEPTED_FILE_TYPES = QA_SIGNOFF_ALLOWED_EXTENSIONS.join(',');

function isAllowedAttachment(file: File): boolean {
  const lowerName = file.name.toLowerCase();
  return QA_SIGNOFF_ALLOWED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
}

export default function NewReleaseModal({
  isOpen,
  onClose,
  onSubmit,
  submitting = false,
  submitError = null,
}: NewReleaseModalProps) {
  const [form, setForm] = useState<NewReleaseForm>(emptyForm);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) {
      setForm(emptyForm);
      setAttachmentError(null);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setAttachmentError(null);

    if (!form.qaSignOff) {
      setAttachmentError('Please choose a QA validation option.');
      return;
    }

    if (form.qaSignOff === 'Upload' && !form.qaSignOffAttachment) {
      setAttachmentError('Please upload the QA sign-off document.');
      return;
    }

    if (form.qaSignOff === 'No' && !form.qaReason.trim()) {
      setAttachmentError('Please provide a reason when QA sign-off is not required.');
      return;
    }

    await onSubmit(form);
  };

  const handleClose = () => {
    setForm(emptyForm);
    setAttachmentError(null);
    onClose();
  };

  const updateField = (field: keyof NewReleaseForm, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleQaSignOffChange = (value: string) => {
    setAttachmentError(null);
    setForm((prev) => ({
      ...prev,
      qaSignOff: value as QaValidationChoice,
      qaReason: value === 'No' ? prev.qaReason : '',
      qaSignOffAttachment: value === 'Upload' ? prev.qaSignOffAttachment : null,
      jira: value === 'GhIssues' ? '' : prev.jira,
    }));
  };

  const handleAttachmentChange = (file: File | null) => {
    setAttachmentError(null);
    if (!file) {
      setForm((prev) => ({ ...prev, qaSignOffAttachment: null }));
      return;
    }

    if (!isAllowedAttachment(file)) {
      setAttachmentError(
        `Unsupported file type. Allowed: ${QA_SIGNOFF_ALLOWED_EXTENSIONS.join(', ')}`
      );
      setForm((prev) => ({ ...prev, qaSignOffAttachment: null }));
      return;
    }

    if (file.size > 10 * 1024 * 1024) {
      setAttachmentError('File size must be 10 MB or less.');
      setForm((prev) => ({ ...prev, qaSignOffAttachment: null }));
      return;
    }

    setForm((prev) => ({ ...prev, qaSignOffAttachment: file }));
  };

  return (
    <div className="modal-overlay" onClick={handleClose} role="presentation">
      <div
        className="modal-content"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div className="modal-header">
          <h2 id="modal-title">Create Release Request</h2>
          <button type="button" className="modal-close" onClick={handleClose} aria-label="Close">
            &times;
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label htmlFor="releaseBranch">Release Branch</label>
              <input
                id="releaseBranch"
                type="text"
                value={form.releaseBranch}
                onChange={(e) => updateField('releaseBranch', e.target.value)}
                placeholder="e.g. release/v2.4.0"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="pr">PR</label>
              <input
                id="pr"
                type="text"
                value={form.pr}
                onChange={(e) => updateField('pr', e.target.value)}
                placeholder="GitHub PR URL"
                required
              />
            </div>
            {form.qaSignOff === 'GhIssues' ? (
              <div className="form-group">
                <span className="form-label">GitHub Issues</span>
                <p className="field-hint">
                  Linked from the PR. Add <code>Fixes #12</code> or a full issue URL in the PR
                  title, description, or comments. Unlinked issues are ignored.
                </p>
              </div>
            ) : (
              <div className="form-group">
                <label htmlFor="jira">JIRA</label>
                <input
                  id="jira"
                  type="text"
                  value={form.jira}
                  onChange={(e) => updateField('jira', e.target.value)}
                  placeholder="Jira URL"
                  required
                />
              </div>
            )}
            <div className="form-group">
              <span className="form-label">QA validation</span>
              <div className="radio-group radio-group-stacked" role="radiogroup" aria-label="QA validation">
                <label className="radio-option">
                  <input
                    type="radio"
                    name="qaSignOff"
                    value="Upload"
                    checked={form.qaSignOff === 'Upload'}
                    onChange={(e) => handleQaSignOffChange(e.target.value)}
                  />
                  <span>Upload QA sign-off document</span>
                </label>
                <label className="radio-option">
                  <input
                    type="radio"
                    name="qaSignOff"
                    value="PrTests"
                    checked={form.qaSignOff === 'PrTests'}
                    onChange={(e) => handleQaSignOffChange(e.target.value)}
                  />
                  <span>Use live Jira + GitHub evidence (no document)</span>
                </label>
                <label className="radio-option">
                  <input
                    type="radio"
                    name="qaSignOff"
                    value="GhIssues"
                    checked={form.qaSignOff === 'GhIssues'}
                    onChange={(e) => handleQaSignOffChange(e.target.value)}
                  />
                  <span>Use live GitHub issues + GitHub evidence (no document)</span>
                </label>
                <label className="radio-option">
                  <input
                    type="radio"
                    name="qaSignOff"
                    value="No"
                    checked={form.qaSignOff === 'No'}
                    onChange={(e) => handleQaSignOffChange(e.target.value)}
                  />
                  <span>Not required</span>
                </label>
              </div>
            </div>
            {form.qaSignOff === 'Upload' && (
              <div className="form-group">
                <label htmlFor="qaSignOffAttachment">QA Sign-off Attachment</label>
                <input
                  id="qaSignOffAttachment"
                  className="file-input"
                  type="file"
                  accept={ACCEPTED_FILE_TYPES}
                  onChange={(e) => handleAttachmentChange(e.target.files?.[0] ?? null)}
                  required
                />
                <p className="field-hint">
                  Upload a QA sign-off document (.docx or .json; max 10 MB). The PR Title
                  field inside the document must match the GitHub PR title.
                </p>
                {form.qaSignOffAttachment && (
                  <p className="file-selected">
                    Selected: {form.qaSignOffAttachment.name}
                  </p>
                )}
              </div>
            )}
            {form.qaSignOff === 'PrTests' && (
              <div className="form-group">
                <p className="field-hint">
                  No QA document needed. The agent uses the live Jira ticket plus this PR:
                  test files in the diff, related tests already in the repo at the commit SHA,
                  the PR Testing / verification write-up, and GitHub check status. If every
                  AC is covered, QA passes. If not, Lane 2 drafts tests for a developer to
                  review, commit, then create a new release.
                </p>
              </div>
            )}
            {form.qaSignOff === 'GhIssues' && (
              <div className="form-group">
                <p className="field-hint">
                  No QA document needed. The agent reads GitHub issues linked from this PR
                  (Fixes #12, issue URLs) and maps those acceptance criteria to PR tests,
                  related repo tests, the PR Testing write-up, and GitHub check status.
                  Unlinked issues are ignored.
                </p>
              </div>
            )}
            {form.qaSignOff === 'No' && (
              <div className="form-group">
                <label htmlFor="qaReason">QA Sign-off Not Required Reason</label>
                <textarea
                  id="qaReason"
                  value={form.qaReason}
                  onChange={(e) => updateField('qaReason', e.target.value)}
                  placeholder="Reason if QA sign-off is not required"
                  rows={3}
                  required
                />
              </div>
            )}
            <div className="form-group">
              <label htmlFor="environment">Environment to be Deployed</label>
              <input
                id="environment"
                type="text"
                value={form.environment}
                onChange={(e) => updateField('environment', e.target.value)}
                placeholder="e.g. UAT2"
                required
              />
            </div>
            <div className="form-group">
              <label htmlFor="releaseDate">Release Date</label>
              <input
                id="releaseDate"
                type="date"
                value={form.releaseDate}
                onChange={(e) => updateField('releaseDate', e.target.value)}
                required
              />
            </div>
          </div>
          {(submitError || attachmentError) && (
            <div className="form-error" role="alert">
              {attachmentError || submitError}
            </div>
          )}
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={handleClose} disabled={submitting}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Submitting…' : 'Submit'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
