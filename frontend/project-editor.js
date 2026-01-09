(function (window, document) {
  "use strict";

  const API_BASE = "/api/projects";

  const ProjectEditor = {
    _inited: false,
    _overlayEl: null,
    _formEl: null,
    _statusEl: null,
    _saveBtnEl: null,
    _currentProject: null,

    _fieldIds: {
      name: "pe-name",
      architect: "pe-architect",
      location: "pe-location",
      category: "pe-category",
      year: "pe-year",
      display_order: "pe-order",
      description: "pe-description",
      tags_text: "pe-tags",
    },

    init() {
      if (this._inited) return;
      this._createDom();
      this._bindEvents();
      this._inited = true;
    },

    open(project) {
      if (!project || !project.id) {
        console.warn("ProjectEditor.open 需要一个带 id 的项目对象");
        return;
      }
      this.init();
      this._currentProject = project;
      this._fillForm(project);
      this._setStatus("");
      this._toggleOverlay(true);
    },

    close() {
      this._toggleOverlay(false);
      this._currentProject = null;
    },

    // ===== 内部实现 =====

    _createDom() {
      const overlay = document.createElement("div");
      overlay.className = "pe-overlay";
      overlay.innerHTML = `
        <div class="pe-modal" role="dialog" aria-modal="true" aria-labelledby="pe-title">
          <div class="pe-header">
            <h2 class="pe-title" id="pe-title">编辑项目信息</h2>
            <button type="button" class="pe-close-btn" aria-label="关闭">×</button>
          </div>
          <div class="pe-body">
            <form class="pe-form">
              <div class="pe-form-row pe-form-row-full">
                <label class="pe-label" for="pe-name">项目名称</label>
                <input id="pe-name" class="pe-input" type="text" autocomplete="off" />
              </div>

              <div class="pe-form-row">
                <label class="pe-label" for="pe-architect">建筑师 / 设计单位</label>
                <input id="pe-architect" class="pe-input" type="text" autocomplete="off" />
              </div>

              <div class="pe-form-row">
                <label class="pe-label" for="pe-location">地点</label>
                <input id="pe-location" class="pe-input" type="text" autocomplete="off" />
              </div>

              <div class="pe-form-row">
                <label class="pe-label" for="pe-category">类别</label>
                <input id="pe-category" class="pe-input" type="text" placeholder="例如：体育建筑、文化建筑…" autocomplete="off" />
              </div>

              <div class="pe-form-row">
                <label class="pe-label" for="pe-year">年份</label>
                <input id="pe-year" class="pe-input" type="text" inputmode="numeric" placeholder="例如：2024" autocomplete="off" />
              </div>

              <div class="pe-form-row pe-form-row-full">
                <label class="pe-label" for="pe-tags">标签（可选，空格分隔）</label>
                <input
                  id="pe-tags"
                  class="pe-input"
                  type="text"
                  placeholder="例如：体育 体育馆 大型赛事"
                  autocomplete="off"
                />
              </div>

              <div class="pe-form-row pe-form-row-full">
                <label class="pe-label" for="pe-order">排序权重（可选，越大越靠前）</label>
                <input id="pe-order" class="pe-input" type="text" inputmode="numeric" autocomplete="off" />
              </div>

              <div class="pe-form-row pe-form-row-full">
                <label class="pe-label" for="pe-description">简介</label>
                <textarea id="pe-description" class="pe-textarea"></textarea>
              </div>
            </form>
          </div>
          <div class="pe-footer">
            <div class="pe-status" id="pe-status"></div>
            <div class="pe-btn-group">
              <button type="button" class="pe-btn" data-role="cancel">取消</button>
              <button type="button" class="pe-btn pe-btn-primary" data-role="save">保存</button>
            </div>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      this._overlayEl = overlay;
      this._formEl = overlay.querySelector(".pe-form");
      this._statusEl = overlay.querySelector("#pe-status");
      this._saveBtnEl = overlay.querySelector('[data-role="save"]');
    },

    _bindEvents() {
      if (!this._overlayEl) return;

      // 统一在 overlay 上做事件委托，但不再响应“点空白关闭”
      this._overlayEl.addEventListener("click", (evt) => {
        const target = evt.target;

        // 点右上角 X 或“取消”按钮关闭
        if (
          target.classList.contains("pe-close-btn") ||
          target.getAttribute("data-role") === "cancel"
        ) {
          this.close();
          return;
        }

        // 点“保存”按钮
        if (target.getAttribute("data-role") === "save") {
          this._handleSave();
        }

        // 点击遮罩层空白区域现在不做任何事
      });

      // （可选）Esc 关闭，如果你不想要可以删掉这段
      document.addEventListener("keydown", (evt) => {
        if (evt.key === "Escape" && this._overlayEl?.classList.contains("pe-open")) {
          this.close();
        }
      });
    },

    _fillForm(project) {
      const get = (key, fallback = "") =>
        project[key] !== null && project[key] !== undefined
          ? String(project[key])
          : fallback;

      this._getInput("name").value = get("name");
      this._getInput("architect").value = get("architect");
      this._getInput("location").value = get("location");
      this._getInput("category").value = get("category");
      this._getInput("year").value = get("year", "");
      this._getInput("display_order").value = get("display_order", "");
      this._getInput("description").value = get("description");
      const tagsInput = this._getInput("tags_text");
      if (tagsInput) {
        if (Array.isArray(project.tags) && project.tags.length) {
          // 后端返回的 tags 列表
          tagsInput.value = project.tags.join(" ");
        } else if (typeof project.tags_text === "string") {
          // 兼容以后可能的 tags_text 字段
          tagsInput.value = project.tags_text;
        } else {
          tagsInput.value = "";
        }
      }
    },

    _getInput(field) {
      const id = this._fieldIds[field];
      return this._overlayEl.querySelector("#" + id);
    },

    _toggleOverlay(show) {
      if (!this._overlayEl) return;
      if (show) {
        this._overlayEl.classList.add("pe-open");
      } else {
        this._overlayEl.classList.remove("pe-open");
      }
    },

    _setStatus(msg, isError) {
      if (!this._statusEl) return;
      this._statusEl.textContent = msg || "";
      this._statusEl.classList.toggle("pe-status-error", !!isError);
    },

    async _handleSave() {
      if (!this._currentProject) return;

      const name = this._getInput("name").value.trim();
      if (!name) {
        this._setStatus("项目名称不能为空", true);
        return;
      }

      const architect = this._getInput("architect").value.trim();
      const location = this._getInput("location").value.trim();
      const category = this._getInput("category").value.trim();
      const description = this._getInput("description").value.trim();

      const yearRaw = this._getInput("year").value.trim();
      const orderRaw = this._getInput("display_order").value.trim();
      const tagsText = this._getInput("tags_text").value.trim();

      let year = null;
      if (yearRaw !== "") {
        const y = parseInt(yearRaw, 10);
        if (!Number.isFinite(y)) {
          this._setStatus("年份必须是数字", true);
          return;
        }
        year = y;
      }

      let display_order = null;
      if (orderRaw !== "") {
        const o = parseInt(orderRaw, 10);
        if (!Number.isFinite(o)) {
          this._setStatus("排序权重必须是数字", true);
          return;
        }
        display_order = o;
      }

      const payload = {
        name,
        architect: architect || null,
        location: location || null,
        category: category || null,
        description: description || null,
        year,
        display_order,
        // 空字符串表示“清空标签”
        tags_text: tagsText,
      };


      this._setStatus("保存中…");
      this._setSaving(true);

      try {
        const updated = await this._requestUpdate(
          this._currentProject.id,
          payload
        );
        this._currentProject = updated;
        this._setStatus("已保存");

        // 通知外部刷新列表（如果你定义了回调）
        if (typeof window.caseLibOnProjectUpdated === "function") {
          window.caseLibOnProjectUpdated(updated);
        }

        setTimeout(() => this.close(), 250);
      } catch (err) {
        console.error(err);
        this._setStatus(
          err && err.message ? err.message : "保存失败",
          true
        );
      } finally {
        this._setSaving(false);
      }
    },

    _setSaving(isSaving) {
      if (!this._saveBtnEl) return;
      this._saveBtnEl.disabled = isSaving;
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
  };

  window.ProjectEditor = ProjectEditor;
})(window, document);
