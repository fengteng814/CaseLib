// frontend/project-batch-editor.js
(function (window, document) {
  "use strict";

  const API_BASE = "/api/projects";

  const ProjectBatchEditor = {
    _inited: false,
    _overlayEl: null,
    _statusEl: null,
    _countEl: null,
    _saveBtnEl: null,
    _mergeBtnEl: null, // ★ 新增：合并按钮引用
    _currentIds: [],

    _fieldIds: {
      name: "pbe-name",
      architect: "pbe-architect",
      location: "pbe-location",
      category: "pbe-category",
      year: "pbe-year",
      display_order: "pbe-order",
      description: "pbe-description",
    },

    init() {
      if (this._inited) return;
      this._createDom();
      this._bindEvents();
      this._inited = true;
    },

    open(projectIds) {
      if (!Array.isArray(projectIds) || projectIds.length === 0) {
        console.warn("ProjectBatchEditor.open 需要至少一个项目 id");
        return;
      }
      this.init();
      this._currentIds = projectIds.slice();
      if (this._countEl) {
        this._countEl.textContent = String(projectIds.length);
      }
      // 选中数量少于 2 个时，禁用“合并项目”按钮
      if (this._mergeBtnEl) {
        this._mergeBtnEl.disabled = projectIds.length < 2;
      }
      this._resetForm();
      this._setStatus("");
      this._toggleOverlay(true);
    },

    close() {
      this._toggleOverlay(false);
      this._currentIds = [];
    },

    // ===== 内部实现 =====

    _createDom() {
      const overlay = document.createElement("div");
      overlay.className = "pbe-overlay";
      overlay.innerHTML = `
        <div class="pbe-modal" role="dialog" aria-modal="true" aria-labelledby="pbe-title">
          <div class="pbe-header">
            <h2 class="pbe-title" id="pbe-title">批量编辑项目</h2>
            <button type="button" class="pbe-close-btn" aria-label="关闭">×</button>
          </div>
          <div class="pbe-body">
            <p class="pbe-tip">
              已选择 <strong class="pbe-count">0</strong> 个项目
            </p>
            <form class="pbe-form">
              <div class="pbe-form-row">
                <div class="pbe-row-header">
                  <label class="pbe-toggle">
                    <input type="checkbox" data-field="architect" />
                    <span>建筑师 / 设计单位</span>
                  </label>
                </div>
                <input id="pbe-architect" class="pbe-input" type="text" autocomplete="off" />
              </div>

              <div class="pbe-form-row">
                <div class="pbe-row-header">
                  <label class="pbe-toggle">
                    <input type="checkbox" data-field="location" />
                    <span>地点</span>
                  </label>
                </div>
                <input id="pbe-location" class="pbe-input" type="text" autocomplete="off" />
              </div>

              <div class="pbe-form-row">
                <div class="pbe-row-header">
                  <label class="pbe-toggle">
                    <input type="checkbox" data-field="category" />
                    <span>类别</span>
                  </label>
                </div>
                <input
                  id="pbe-category"
                  class="pbe-input"
                  type="text"
                  placeholder="例如：体育建筑、文化建筑…"
                  autocomplete="off"
                />
              </div>

              <div class="pbe-form-row">
                <div class="pbe-row-header">
                  <label class="pbe-toggle">
                    <input type="checkbox" data-field="year" />
                    <span>年份</span>
                  </label>
                </div>
                <input
                  id="pbe-year"
                  class="pbe-input"
                  type="text"
                  inputmode="numeric"
                  placeholder="例如：2024"
                  autocomplete="off"
                />
              </div>

              <div class="pbe-form-row">
                <div class="pbe-row-header">
                  <label class="pbe-toggle">
                    <input type="checkbox" data-field="display_order" />
                    <span>排序权重（越大越靠前）</span>
                  </label>
                </div>
                <input
                  id="pbe-order"
                  class="pbe-input"
                  type="text"
                  inputmode="numeric"
                  autocomplete="off"
                />
              </div>

              <div class="pbe-form-row">
                <div class="pbe-row-header">
                  <label class="pbe-toggle">
                    <input type="checkbox" data-field="description" />
                    <span>简介</span>
                  </label>
                </div>
                <textarea id="pbe-description" class="pbe-textarea"></textarea>
              </div>
            </form>
          </div>
          <div class="pbe-footer">
            <div class="pbe-status"></div>
            <div class="pbe-btn-group">
              <button type="button" class="pbe-btn pbe-btn-ghost" data-role="cancel">取消</button>
              <button type="button" class="pbe-btn" data-role="merge">
                合并为一个项目
              </button>
              <button type="button" class="pbe-btn pbe-btn-primary" data-role="apply">
                应用到项目
              </button>
            </div>
          </div>
        </div>
      `;

      document.body.appendChild(overlay);

      this._overlayEl = overlay;
      this._statusEl = overlay.querySelector(".pbe-status");
      this._countEl = overlay.querySelector(".pbe-count");
      this._saveBtnEl = overlay.querySelector('[data-role="apply"]');
      this._mergeBtnEl = overlay.querySelector('[data-role="merge"]');
    },

    _bindEvents() {
      if (!this._overlayEl) return;

      this._overlayEl.addEventListener("click", (evt) => {
        const target = evt.target;

        // 点遮罩空白处关闭
        if (target.classList.contains("pbe-overlay")) {
          this.close();
          return;
        }

        if (
          target.classList.contains("pbe-close-btn") ||
          target.getAttribute("data-role") === "cancel"
        ) {
          this.close();
          return;
        }

        if (target.getAttribute("data-role") === "apply") {
          this._handleApply();
          return;
        }

        if (target.getAttribute("data-role") === "merge") {
          this._handleMerge();
          return;
        }
      });
    },

    _resetForm() {
      if (!this._overlayEl) return;
      Object.keys(this._fieldIds).forEach((field) => {
        const input = this._getInput(field);
        if (!input) return;
        if (input.tagName === "TEXTAREA") {
          input.value = "";
        } else {
          input.value = "";
        }
        const toggle = this._getToggle(field);
        if (toggle) {
          toggle.checked = false;
        }
      });
    },

    _getInput(field) {
      const id = this._fieldIds[field];
      if (!id || !this._overlayEl) return null;
      return this._overlayEl.querySelector("#" + id);
    },

    _getToggle(field) {
      if (!this._overlayEl) return null;
      return this._overlayEl.querySelector(
        'input[type="checkbox"][data-field="' + field + '"]'
      );
    },

    _toggleOverlay(show) {
      if (!this._overlayEl) return;
      if (show) {
        this._overlayEl.classList.add("pbe-open");
      } else {
        this._overlayEl.classList.remove("pbe-open");
      }
    },

    _setStatus(msg, isError) {
      if (!this._statusEl) return;
      this._statusEl.textContent = msg || "";
      this._statusEl.classList.toggle("pbe-status-error", !!isError);
    },

    async _handleApply() {
      if (!this._currentIds || !this._currentIds.length) return;

      // 构造一次性 payload（对所有项目一致）
      const payload = {};
      let hasField = false;

      const scalarFields = [
        "architect",
        "location",
        "category",
        "year",
        "display_order",
        "description",
      ];

      for (const field of scalarFields) {
        const toggle = this._getToggle(field);
        if (!toggle || !toggle.checked) continue;

        const input = this._getInput(field);
        if (!input) continue;

        let value = input.value.trim();
        hasField = true;

        if (field === "year" || field === "display_order") {
          if (value === "") {
            value = null;
          } else {
            const num = parseInt(value, 10);
            if (!Number.isFinite(num)) {
              this._setStatus(
                field === "year" ? "年份必须是数字" : "排序权重必须是数字",
                true
              );
              return;
            }
            value = num;
          }
        } else {
          if (value === "") {
            value = null;
          }
        }

        payload[field] = value;
      }

      if (!hasField) {
        this._setStatus("请至少勾选一个字段再保存", true);
        return;
      }

      this._setStatus("批量保存中…");
      this._setSaving(true);

      try {
        // 对每个项目依次调用 PUT /api/projects/{id}
        const promises = this._currentIds.map((id) =>
          this._requestUpdate(id, payload)
        );
        const results = await Promise.all(promises);

        this._setStatus("已保存");
        if (typeof window.caseLibOnProjectsBatchUpdated === "function") {
          window.caseLibOnProjectsBatchUpdated(results);
        }

        setTimeout(() => this.close(), 250);
      } catch (err) {
        console.error(err);
        this._setStatus(
          err && err.message ? err.message : "批量保存失败",
          true
        );
      } finally {
        this._setSaving(false);
      }
    },

    // ★ 新增：处理“合并为一个项目”
    async _handleMerge() {
      if (!this._currentIds || this._currentIds.length < 2) {
        this._setStatus("合并项目至少需要 2 个项目", true);
        return;
      }

      const ids = this._currentIds;
      const targetId = ids[0];
      const sourceIds = ids.slice(1);

      const ok = window.confirm(
        "将把其它 " +
          sourceIds.length +
          " 个项目合并到第一个选中的项目，并删除其它项目。\n此操作不可撤销，确定继续？"
      );
      if (!ok) return;

      this._setStatus("正在合并项目…");
      this._setSaving(true);

      try {
        const result = await this._requestMerge(targetId, sourceIds);
        this._setStatus("合并完成");

        if (typeof window.caseLibOnProjectsMerged === "function") {
          // 如果你在 app.js 里定义了这个回调，就交给它来更新列表
          window.caseLibOnProjectsMerged(result);
          this.close();
        } else {
          // 简单粗暴：刷新页面，重新加载项目列表
          window.location.reload();
        }
      } catch (err) {
        console.error(err);
        this._setStatus(
          err && err.message ? err.message : "合并失败",
          true
        );
      } finally {
        this._setSaving(false);
      }
    },

    _setSaving(isSaving) {
      if (this._saveBtnEl) {
        this._saveBtnEl.disabled = isSaving;
      }
      if (this._mergeBtnEl) {
        this._mergeBtnEl.disabled = isSaving;
      }
    },

    async _requestUpdate(id, payload) {
      const res = await fetch(`${API_BASE}/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          if (data && data.detail) {
            msg = data.detail;
          }
        } catch (_) {
          // ignore
        }
        throw new Error(msg);
      }

      return res.json();
    },

    // ★ 新增：请求后端合并接口
    async _requestMerge(targetId, sourceIds) {
      const res = await fetch(`${API_BASE}/merge`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          target_id: targetId,
          source_ids: sourceIds,
        }),
      });

      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const data = await res.json();
          if (data && data.detail) {
            msg = data.detail;
          }
        } catch (_) {
          // ignore
        }
        throw new Error(msg);
      }

      return res.json();
    },
  };

  window.ProjectBatchEditor = ProjectBatchEditor;
})(window, document);
