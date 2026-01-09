(function () {
  console.log(
    "CaseLib frontend app.js loaded (masonry + lightbox + edit mode + thumbs + cover + copy path + scroll + search debounce + refresh + back-to-top + sticky-header + paged-projects + hot-tags + sort + favorites)"
  );

  // ------- DOM 元素 -------

  const projectsTabBtn = document.querySelector(
    '.tab-button[data-tab="projects"]'
  );
  const waterfallTabBtn = document.querySelector(
    '.tab-button[data-tab="waterfall"]'
  );

  const projectsTabPanel = document.getElementById("tab-projects");
  const waterfallTabPanel = document.getElementById("tab-waterfall");

  const projectsContainer = document.getElementById("projects-container");
  const waterfallContainer = document.getElementById("waterfall-container");

  const searchInput = document.getElementById("search-input");
  const searchBtn = document.getElementById("search-btn");
  const searchClearBtn = document.getElementById("search-clear-btn");
  const refreshProjectsBtn = document.getElementById("refresh-projects-btn");
  const openImportBtn = document.getElementById("open-web-import-btn");
  const sortSelect = document.getElementById("sort-select");
  // 兼容两种写法：优先用 #tag-strip，没有的话退回 #hot-tags-container
  const tagStripEl =
    document.getElementById("tag-strip") ||
    document.getElementById("hot-tags-container");

  const appHeader = document.querySelector(".app-header");
  const backToTopBtn = document.getElementById("back-to-top");
  const toggleEditModeBtn = document.getElementById("toggle-edit-mode-btn");
  const toolbarEl = document.querySelector(".toolbar");

  // 收藏夹视图 banner 容器（具体内容交给 favorites.js 管）
  let collectionBannerEl = null;

  // 对齐 CSS 类名
  if (
    projectsContainer &&
    !projectsContainer.classList.contains("projects-grid")
  ) {
    projectsContainer.classList.add("projects-grid");
  }
  if (
    waterfallContainer &&
    !waterfallContainer.classList.contains("waterfall-grid")
  ) {
    waterfallContainer.classList.add("waterfall-grid");
  }

  // ------- 页面状态 -------

  let activeTab = "projects";
  let currentProjects = [];
  let allProjects = []; // 已加载的项目（分页叠加），用于本地搜索过滤
  let projectsScrollY = 0; // 项目页滚动位置，用于返回时恢复

  // 当前排序方式（和后端 API sort 参数对应）
  let currentSort = "updated";
  // 同步默认选中值到 currentSort（比如 "updated"）
  if (sortSelect) {
    sortSelect.value = currentSort;  // currentSort 已经被你改成 "updated"
  }

  // 当前是否在“收藏夹视图”中（否则为 null）
  let activeCollectionFilter = null; // { id, name, visibility } 或 null

  // 项目分页：首页只读 X 个，下拉再读 Y 个（从后端配置覆盖）
  const projectPaging = {
    initialLimit: 60, // 默认值：会被 /api/frontend-config 覆盖
    pageSize: 30, // 默认值
    offset: 0,
    loading: false,
    hasMore: true,
    configLoaded: false,
  };

  // 标签 / 热词相关
  let hotTagLimit = 10;
  const LAST_COLLECTION_KEY = "caselib:last-collection";

  let fixedTags = []; // 来自 config.ini 的固定标签
  let hotKeywords = []; // 来自后端的全站热词

  // 编辑模式 & 多选状态
  let editMode = false;
  const selectedProjectIds = new Set();

  // 瀑布流图片分页状态
  const imageState = {
    items: [], // 已加载的所有图片（保持顺序）
    limit: 30, // 每页多少张（也会被 /api/frontend-config 覆盖）
    offset: 0,
    loading: false,
    hasMore: true,
    activeQuery: "",
    activeProjectId: null,
  };

  // ------- 瀑布流列布局状态 -------

  let waterfallCols = [];
  let waterfallColCount = 0;
  let lastColCount = 0;

  // ------- Toast -------

  let toastTimer = null;

  function showToast(message) {
    if (!message) return;
    let toast = document.getElementById("cslb-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "cslb-toast";
      toast.className = "cslb-toast";
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("visible");
    if (toastTimer) {
      clearTimeout(toastTimer);
    }
    toastTimer = setTimeout(() => {
      toast.classList.remove("visible");
    }, 2000);
  }

  // ------- 监听 Web 导入完成通知（localStorage） -------

  window.addEventListener("storage", (event) => {
    if (event.key !== "caselib:web-import:last") return;
    if (!event.newValue) return;
    let payload;
    try {
      payload = JSON.parse(event.newValue);
    } catch (e) {
      console.warn("解析 web-import 通知失败：", e);
      return;
    }
    if (!payload || !payload.status) return;

    if (payload.status === "done") {
      const name = payload.projectName || "新项目";
      showToast(`已从网站导入项目：${name}（记得刷新案例库）`);
    } else if (payload.status === "error") {
      const msg = payload.message ? String(payload.message) : "";
      showToast(`从网站导入失败：${msg}`);
    }
  });

  // ------- 工具：复制到剪贴板 -------

  async function copyTextToClipboard(text) {
    if (!text) return;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
          document.execCommand("copy");
        } catch (e) {
          console.warn("document.execCommand('copy') 失败：", e);
        }
        document.body.removeChild(textarea);
      }
      showToast("路径已复制");
    } catch (e) {
      console.warn("复制到剪贴板失败：", e);
      showToast("复制失败");
    }
  }

  // ------- 工具：防抖 -------

  function debounce(fn, delay) {
    let timer = null;
    return function (...args) {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  // ------- 搜索框 X 按钮显隐 -------

  function updateSearchClearVisibility() {
    if (!searchInput || !searchClearBtn) return;
    const hasValue = !!(searchInput.value && searchInput.value.trim());
    searchClearBtn.classList.toggle("visible", hasValue);
  }

  // 从后端加载全站热词
  async function loadHotKeywordsFromServer() {
    try {
      const res = await fetch("/api/hot_keywords");
      if (!res.ok) {
        console.warn("加载全站热词失败，status=", res.status);
        hotKeywords = [];
        renderTagStrip();
        return;
      }
      const data = await res.json();
      if (Array.isArray(data)) {
        hotKeywords = data;
      } else {
        hotKeywords = [];
      }
      renderTagStrip();
    } catch (e) {
      console.warn("加载全站热词异常：", e);
      hotKeywords = [];
      renderTagStrip();
    }
  }

  // 向后端记录一次搜索关键词（只做统计，失败忽略）
  async function recordSearchKeyword(raw) {
    if (!raw) return;
    const q = raw.trim();
    if (!q) return;
    try {
      await fetch("/api/search_keywords", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q }),
      });
    } catch (e) {
      console.warn("记录搜索关键词失败（忽略）：", e);
    }
  }

  // 渲染“固定标签 + 热词标签”在同一条标签栏里

  function renderTagStrip() {
    if (!tagStripEl) return;

    // 确保有统一的样式类
    tagStripEl.classList.add("tag-strip");
    tagStripEl.innerHTML = "";

    const used = new Set();
    let hasAnyTag = false;

    function ensureLabel() {
      if (hasAnyTag) return;
      const labelSpan = document.createElement("span");
      labelSpan.className = "hot-tags-label";
      labelSpan.textContent = "常用及热词";
      tagStripEl.appendChild(labelSpan);
      hasAnyTag = true;
    }

    function addTag(label, type) {
      const text = String(label || "").trim();
      if (!text) return;
      const lower = text.toLowerCase();
      if (used.has(lower)) return;
      used.add(lower);

      // 第一次真正有标签时才插入“常用及热词”标签
      ensureLabel();

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tag-pill" + (type ? " " + type : "");
      btn.textContent = text;

      btn.addEventListener("click", () => {
        if (!searchInput) return;
        searchInput.value = text;
        updateSearchClearVisibility();

        if (activeTab === "projects") {
          applyProjectFilter();
        } else {
          fetchImagesPage({ reset: true, query: text });
        }

        // 点击标签时也记录一次搜索
        recordSearchKeyword(text);
        // 然后后台统计可能变化，异步刷新一遍热词栏
        loadHotKeywordsFromServer();
      });

      tagStripEl.appendChild(btn);
    }

    // 先画固定标签（config.ini 里的）
    if (Array.isArray(fixedTags) && fixedTags.length) {
      fixedTags.forEach((t) => addTag(t, "tag-fixed"));
    }

    // 再画全站热词标签（后端统计的搜索词）
    if (Array.isArray(hotKeywords) && hotKeywords.length) {
      const limit = hotTagLimit || 10;
      let count = 0;
      for (const item of hotKeywords) {
        if (count >= limit) break;
        const label =
          item && typeof item.keyword === "string"
            ? item.keyword
            : typeof item === "string"
              ? item
              : "";
        if (!label) continue;
        addTag(label, "tag-hot");
        count++;
      }
    }

    // 没有任何标签时整条隐藏
    if (!hasAnyTag) {
      tagStripEl.style.display = "none";
    } else {
      tagStripEl.style.display = "";
    }
  }

  // ------- 瀑布流：列数计算 & 重排 -------

  function computeColumnCount() {
    const w =
      window.innerWidth || document.documentElement.clientWidth || 1200;
    if (w <= 768) return 2;
    if (w <= 1024) return 3;
    return 4;
  }

  function resetWaterfallLayout() {
    if (!waterfallContainer) return;
    waterfallContainer.innerHTML = "";
    waterfallCols = [];
    waterfallColCount = computeColumnCount();
    if (waterfallColCount <= 0) waterfallColCount = 1;
    lastColCount = waterfallColCount;

    for (let i = 0; i < waterfallColCount; i++) {
      const col = document.createElement("div");
      col.className = "waterfall-column";
      waterfallContainer.appendChild(col);
      waterfallCols.push(col);
    }
  }

  window.addEventListener("resize", () => {
    if (!waterfallContainer) return;
    if (!imageState.items.length) return;

    const newCount = computeColumnCount();
    if (!lastColCount) {
      lastColCount = newCount;
      return;
    }
    if (newCount === lastColCount) return;

    lastColCount = newCount;
    waterfallContainer.innerHTML = "";
    waterfallCols = [];
    waterfallColCount = newCount;
    if (waterfallColCount <= 0) waterfallColCount = 1;
    for (let i = 0; i < waterfallColCount; i++) {
      const col = document.createElement("div");
      col.className = "waterfall-column";
      waterfallContainer.appendChild(col);
      waterfallCols.push(col);
    }

    appendImages(imageState.items, 0);
  });

  // ------- Lightbox 状态 -------

  const lightboxState = {
    isOpen: false,
    currentIndex: 0,
    scale: 1,
    translateX: 0,
    translateY: 0,
  };

  let lightboxOverlay = null;
  let lightboxImg = null;
  let lightboxImgWrap = null;
  let lightboxSetCoverBtn = null;

  // ------- Tab 切换 -------

  function setActiveTab(tabName) {
    activeTab = tabName;

    [projectsTabBtn, waterfallTabBtn].forEach((btn) => {
      if (!btn) return;
      const tab = btn.dataset.tab;
      if (tab === tabName) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    if (projectsTabPanel && waterfallTabPanel) {
      if (tabName === "projects") {
        projectsTabPanel.classList.add("active");
        waterfallTabPanel.classList.remove("active");
      } else {
        waterfallTabPanel.classList.add("active");
        projectsTabPanel.classList.remove("active");
      }
    }
  }

  // ------- 编辑模式开关 -------

  function setEditMode(on) {
    editMode = !!on;

    document.body.classList.toggle("mode-edit", editMode);

    if (toggleEditModeBtn) {
      toggleEditModeBtn.classList.toggle("edit-on", editMode);
      toggleEditModeBtn.textContent = editMode ? "退出编辑" : "✎ 编辑";
      toggleEditModeBtn.title = editMode ? "退出编辑模式" : "编辑项目";
    }

    if (!editMode) {
      selectedProjectIds.clear();
    }

    renderProjects();
  }

  // ------- 项目搜索过滤（前端本地） -------

  function applyProjectFilter() {
    if (!Array.isArray(allProjects)) {
      currentProjects = [];
      renderProjects();
      return;
    }

    const kw =
      searchInput && searchInput.value
        ? searchInput.value.trim().toLowerCase()
        : "";

    if (!kw) {
      currentProjects = allProjects.slice();
      renderProjects();
      return;
    }

    currentProjects = allProjects.filter((p) => {
      if (!p) return false;
      const fields = [
        p.name,
        p.architect,
        p.location,
        p.category,
        p.year != null ? String(p.year) : "",
      ];

      // 把项目标签也串进搜索字段里
      if (Array.isArray(p.tags) && p.tags.length) {
        fields.push(p.tags.join(" "));
      }

      return fields.some((v) => {
        if (!v) return false;
        return String(v).toLowerCase().includes(kw);
      });
    });

    renderProjects();
  }

  // ------- 读取前端配置（X / Y / 热门标签数量等） -------

  async function loadFrontendConfig() {
    try {
      const res = await fetch("/api/frontend-config");
      if (!res.ok) {
        console.warn("加载前端配置失败，使用默认值，status=", res.status);
        // 配置失败时，至少渲染一次（可能为空）
        renderTagStrip();
        return;
      }
      const cfg = await res.json();
      console.log("DEBUG /api/frontend-config 返回：", cfg);

      if (typeof cfg.project_initial_limit === "number") {
        projectPaging.initialLimit = cfg.project_initial_limit;
      }
      if (typeof cfg.project_page_size === "number") {
        projectPaging.pageSize = cfg.project_page_size;
      }
      if (typeof cfg.image_page_size === "number") {
        imageState.limit = cfg.image_page_size;
      }
      if (typeof cfg.hot_tag_limit === "number") {
        hotTagLimit = cfg.hot_tag_limit;
      }

      // 固定标签（config.ini 里的 fixed_hot_tags）
      if (Array.isArray(cfg.fixed_hot_tags)) {
        fixedTags = cfg.fixed_hot_tags
          .map((s) => (typeof s === "string" ? s.trim() : ""))
          .filter(Boolean);
      } else if (typeof cfg.fixed_hot_tags === "string") {
        fixedTags = cfg.fixed_hot_tags
          .split(/[,\s]+/)
          .map((s) => s.trim())
          .filter(Boolean);
      }

      // 固定标签就绪先渲染一遍，再异步拉取全站热词
      renderTagStrip();
      await loadHotKeywordsFromServer();

      projectPaging.configLoaded = true;
    } catch (e) {
      console.warn("加载前端配置异常，使用默认值：", e);
      renderTagStrip();
      // 尝试仍加载一次全站热词
      await loadHotKeywordsFromServer();
    }
  }

  // ------- 请求项目列表（分页：首页 X 条，下拉再加载 Y 条） -------

  async function fetchProjects(reset = false) {
    if (projectPaging.loading) return;

    if (reset) {
      projectPaging.offset = 0;
      projectPaging.hasMore = true;
      allProjects = [];
      currentProjects = [];

      // 重置全站项目视图时，退出收藏夹视图过滤
      activeCollectionFilter = null;
      updateCollectionBanner();

      if (projectsContainer) {
        projectsContainer.innerHTML = "";
      }
    } else {
      if (!projectPaging.hasMore) return;
    }

    const isFirstPage = projectPaging.offset === 0;
    const limit = isFirstPage
      ? projectPaging.initialLimit
      : projectPaging.pageSize;

    projectPaging.loading = true;

    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(projectPaging.offset));
      params.set("sort", currentSort || "heat");

      const url = "/api/projects?" + params.toString();
      console.log("fetchProjects ->", url);

      const res = await fetch(url);
      if (!res.ok) throw new Error("请求项目列表失败，status=" + res.status);

      const data = await res.json();
      console.log("DEBUG /api/projects 返回：", data);

      let list = [];
      if (Array.isArray(data)) {
        list = data;
      } else if (Array.isArray(data.items)) {
        list = data.items;
      } else if (Array.isArray(data.results)) {
        list = data.results;
      } else {
        console.error("项目列表返回结构不是数组：", data);
        list = [];
      }

      if (isFirstPage) {
        allProjects = list;
      } else {
        allProjects = allProjects.concat(list);
      }

      projectPaging.offset += list.length;
      if (list.length < limit) {
        projectPaging.hasMore = false;
      }

      applyProjectFilter();
      updateCollectionBanner();
    } catch (err) {
      console.error("fetchProjects 出错：", err);
      if (projectsContainer) {
        projectsContainer.innerHTML =
          '<p class="center-hint" style="color:#c00;">加载项目失败，请查看浏览器控制台日志。</p>';
      }
    } finally {
      projectPaging.loading = false;
    }
  }

  // ------- 收藏夹视图 banner -------

  function ensureCollectionBanner() {
    if (!projectsTabPanel || !projectsContainer) return;

    // 已经创建过就不用再创建
    if (collectionBannerEl && collectionBannerEl.parentNode) return;

    const banner = document.createElement("div");
    banner.className = "collection-banner";
    banner.id = "collection-banner";
    banner.style.display = "none"; // 默认隐藏，由 favorites.js 控制显示/内容

    // 插在项目网格的正上方
    projectsTabPanel.insertBefore(banner, projectsContainer);

    collectionBannerEl = banner;
  }

  function updateCollectionBanner() {
    // 现在 banner 的具体内容和显隐逻辑由 favorites.js 接管
    ensureCollectionBanner();
  }

  // 供 favorites.js 调用：进入收藏夹模式时保证 banner 存在
  window.caseLibOnEnterFavoritesMode = function () {
    ensureCollectionBanner();
  };

  // 供 favorites.js 调用：退出收藏夹模式时回到全站项目列表
  window.caseLibOnExitFavoritesMode = function () {
    activeCollectionFilter = null;
    projectPaging.offset = 0;
    projectPaging.hasMore = true;
    projectPaging.loading = false;

    setActiveTab("projects");

    if (searchInput) {
      searchInput.value = "";
      updateSearchClearVisibility();
    }

    fetchProjects(true);
    window.scrollTo(0, 0);
  };

  // ------- 拖拽到项目卡片：解析 HTML 中的 <img> -------

  function extractImageUrlsFromHtml(html) {
    if (!html) return [];
    const div = document.createElement("div");
    div.innerHTML = html;
    const imgs = Array.from(div.querySelectorAll("img"));
    return imgs
      .map((img) => img.src)
      .filter((u) => typeof u === "string" && u.trim().length > 0);
  }

  // ------- 绑定项目卡片的拖拽上传区域 -------

  function bindCardDropArea(cardEl) {
    if (!cardEl) return;
    const projectId = cardEl.dataset.id;
    if (!projectId) return;

    // 防止重复绑定
    if (cardEl.dataset.dropBound === "1") return;
    cardEl.dataset.dropBound = "1";

    function preventDefaults(e) {
      e.preventDefault();
      e.stopPropagation();
    }

    ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
      cardEl.addEventListener(eventName, preventDefaults, false);
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      cardEl.addEventListener(
        eventName,
        () => {
          cardEl.classList.add("drop-hover");
        },
        false
      );
    });

    ["dragleave", "drop"].forEach((eventName) => {
      cardEl.addEventListener(
        eventName,
        () => {
          cardEl.classList.remove("drop-hover");
        },
        false
      );
    });

    cardEl.addEventListener("drop", (e) => {
      handleCardDrop(e, projectId, cardEl);
    });
  }

  // ------- 处理拖拽到卡片上的数据 -------

  async function handleCardDrop(e, projectId, cardEl) {
    const dt = e.dataTransfer;
    if (!dt) return;

    const formData = new FormData();
    const files = dt.files;

    // 1) 本地文件（资源管理器等）
    if (files && files.length > 0) {
      Array.from(files).forEach((file) => {
        if (!file) return;
        const isImageType =
          file.type && typeof file.type === "string"
            ? file.type.startsWith("image/")
            : false;
        const hasImageExt = /\.(jpg|jpeg|png|gif|webp|tif|tiff)$/i.test(
          file.name || ""
        );
        if (isImageType || hasImageExt) {
          formData.append("files", file);
        }
      });
    }

    // 2) 外部图片 URL（浏览器 / 微信文章里拖拽）
    const urlsSet = new Set();

    try {
      const uriList = dt.getData("text/uri-list");
      if (uriList) {
        uriList
          .split("\n")
          .map((l) => l.trim())
          .filter((l) => l && !l.startsWith("#"))
          .forEach((u) => urlsSet.add(u));
      }
    } catch (err) {
      console.warn("读取 text/uri-list 失败：", err);
    }

    try {
      const html = dt.getData("text/html");
      if (html) {
        extractImageUrlsFromHtml(html).forEach((u) => urlsSet.add(u));
      }
    } catch (err) {
      console.warn("读取 text/html 失败：", err);
    }

    try {
      const text = dt.getData("text/plain");
      if (text && /^https?:\/\//i.test(text.trim())) {
        urlsSet.add(text.trim());
      }
    } catch (err) {
      console.warn("读取 text/plain 失败：", err);
    }

    const urls = Array.from(urlsSet);
    if (urls.length > 0) {
      formData.append("urls", JSON.stringify(urls));
    }

    if (!formData.has("files") && urls.length === 0) {
      showToast("拖入的内容里没有检测到图片");
      return;
    }

    cardEl.classList.add("uploading");
    try {
      const resp = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/images/drop-upload`,
        {
          method: "POST",
          body: formData,
        }
      );
      if (!resp.ok) {
        throw new Error("上传失败，status=" + resp.status);
      }
      const data = await resp.json();
      const count =
        data && typeof data.count === "number" ? data.count : null;

      if (data && data.ok === false && !count) {
        const msg =
          typeof data.message === "string" && data.message
            ? data.message
            : "图片上传失败";
        showToast(msg);
        return;
      }

      if (count && count > 0) {
        showToast(`已添加 ${count} 张图片到该项目`);
      } else {
        showToast("图片已保存到项目文件夹");
      }

      // 这里暂时不自动刷新瀑布流 / 项目封面
      // 如果以后想加：可以判断当前是否在该项目的瀑布流里，然后重新 fetchImagesPage({ reset:true, projectId })
    } catch (err) {
      console.error("拖拽上传失败：", err);
      showToast("图片上传失败");
    } finally {
      cardEl.classList.remove("uploading");
    }
  }

  // ------- 渲染项目卡片（含编辑模式 UI + 复制路径按钮 + 收藏按钮） -------

  function renderProjects() {
    if (!projectsContainer) return;

    projectsContainer.innerHTML = "";

    if (!currentProjects || currentProjects.length === 0) {
      projectsContainer.innerHTML =
        '<p class="center-hint">暂无项目。</p>';
      return;
    }

    currentProjects.forEach((p) => {
      const card = document.createElement("div");
      card.className = "project-card";
      card.dataset.id = String(p.id);

      const initiallySelected = selectedProjectIds.has(p.id);
      if (initiallySelected) {
        card.classList.add("selected");
      }

      // 勾选框
      const selectLabel = document.createElement("label");
      selectLabel.className = "project-select-checkbox";
      if (editMode) {
        selectLabel.classList.add("is-visible");
      }

      const selectInput = document.createElement("input");
      selectInput.type = "checkbox";
      selectInput.checked = initiallySelected;

      selectInput.addEventListener("click", (e) => {
        e.stopPropagation();
      });

      selectInput.addEventListener("change", (e) => {
        const checked = e.target.checked;
        if (checked) {
          selectedProjectIds.add(p.id);
        } else {
          selectedProjectIds.delete(p.id);
        }
        card.classList.toggle("selected", checked);
      });

      selectLabel.appendChild(selectInput);
      card.appendChild(selectLabel);

      // 编辑按钮
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "project-edit-btn";
      editBtn.textContent = "编辑";
      if (editMode) {
        editBtn.classList.add("is-visible");
      }

      editBtn.addEventListener("click", (e) => {
        e.stopPropagation();

        const selectedCount = selectedProjectIds.size;

        if (
          selectedCount >= 2 &&
          window.ProjectBatchEditor &&
          typeof window.ProjectBatchEditor.open === "function"
        ) {
          const ids = Array.from(selectedProjectIds);
          window.ProjectBatchEditor.open(ids);
          return;
        }

        if (
          window.ProjectEditor &&
          typeof window.ProjectEditor.open === "function"
        ) {
          window.ProjectEditor.open(p);
        } else {
          console.warn("ProjectEditor 未加载");
        }
      });

      card.appendChild(editBtn);

      // 复制路径按钮
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "project-copy-btn";
      copyBtn.title = "复制项目文件夹路径";
      copyBtn.textContent = "⧉";
      if (!editMode) {
        copyBtn.classList.add("is-visible");
      }

      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (p.fs_path) {
          copyTextToClipboard(p.fs_path);
        } else {
          showToast("没有可复制的路径");
        }
      });

      card.appendChild(copyBtn);

      // 封面
      const coverWrap = document.createElement("div");
      // 增加 project-card-thumb，方便收藏按钮定位
      coverWrap.className = "project-cover project-card-thumb";

      if (p.cover_url) {
        const img = document.createElement("img");
        img.src = p.cover_url;
        img.alt = p.name || "";
        coverWrap.appendChild(img);
      } else {
        const placeholder = document.createElement("div");
        placeholder.className = "project-cover placeholder";
        placeholder.textContent = "暂无封面";
        coverWrap.appendChild(placeholder);
      }

      // 收藏按钮（由 favorites.js 通过 data-action 处理）
      const favBtn = document.createElement("button");
      favBtn.type = "button";
      favBtn.className = "card-fav-btn";
      favBtn.title = "收藏到收藏夹";
      favBtn.setAttribute("data-action", "open-favorite-dialog");
      favBtn.setAttribute("data-project-id", String(p.id));
      favBtn.textContent = "☆";
      coverWrap.appendChild(favBtn);

      // 文本信息
      const info = document.createElement("div");
      info.className = "project-info";

      const title = document.createElement("div");
      title.className = "project-name";
      title.textContent = p.name || "(未命名项目)";
      info.appendChild(title);

      const metaParts = [];
      if (p.architect) metaParts.push(p.architect);
      if (p.location) metaParts.push(p.location);
      if (p.category) metaParts.push(p.category);
      if (p.year) metaParts.push(p.year);

      if (metaParts.length > 0) {
        const meta = document.createElement("div");
        meta.className = "project-meta";
        meta.textContent = metaParts.join(" · ");
        info.appendChild(meta);
      }

      card.appendChild(coverWrap);
      card.appendChild(info);

      // 点击项目卡片 → 进入瀑布流视图 / 编辑模式选择
      card.addEventListener("click", (event) => {
        // 点击收藏按钮时，不触发卡片的默认行为
        if (event.target.closest(".card-fav-btn")) {
          return;
        }

        if (editMode) {
          const isSelected = selectedProjectIds.has(p.id);
          const newState = !isSelected;

          if (newState) {
            selectedProjectIds.add(p.id);
          } else {
            selectedProjectIds.delete(p.id);
          }

          selectInput.checked = newState;
          card.classList.toggle("selected", newState);
        } else {
          // 记录热度
          try {
            fetch(`/api/projects/${p.id}/click`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
            }).catch((err) => {
              console.warn("记录项目点击热度失败：", err);
            });
          } catch (err) {
            console.warn("记录项目点击热度失败：", err);
          }

          // 记住当前滚动位置
          projectsScrollY = window.scrollY || 0;

          // 更新 history
          try {
            if (window.history && "replaceState" in window.history) {
              const currentState = window.history.state || {};
              const projectState = Object.assign({}, currentState, {
                view: "projects",
                projectsScrollY,
              });
              window.history.replaceState(projectState, "");

              const waterfallState = {
                view: "waterfall",
                projectId: p.id,
              };
              window.history.pushState(waterfallState, "");
            }
          } catch (e) {
            console.warn("更新 history state 失败：", e);
          }

          setActiveTab("waterfall");
          window.scrollTo(0, 0);
          fetchImagesPage({
            reset: true,
            projectId: p.id,
          });
        }
      });

      // ★★ 这里绑定拖拽上传行为 ★★
      bindCardDropArea(card);

      projectsContainer.appendChild(card);
    });
  }

  // ------- 单项目更新回调 -------

  window.caseLibOnProjectUpdated = function (updated) {
    if (!updated || typeof updated.id !== "number") return;

    const idxAll = allProjects.findIndex((p) => p.id === updated.id);
    if (idxAll !== -1) {
      allProjects[idxAll] = updated;
    } else {
      allProjects.push(updated);
    }

    const idx = currentProjects.findIndex((p) => p.id === updated.id);
    if (idx !== -1) {
      currentProjects[idx] = updated;
    } else {
      currentProjects.push(updated);
    }

    applyProjectFilter();
  };

  // ------- 批量更新回调 -------

  window.caseLibOnProjectsBatchUpdated = function (updatedList) {
    if (!Array.isArray(updatedList) || !updatedList.length) return;

    const map = new Map();
    updatedList.forEach((p) => {
      if (p && typeof p.id === "number") {
        map.set(p.id, p);
      }
    });

    allProjects = allProjects.map((p) =>
      map.has(p.id) ? map.get(p.id) : p
    );

    currentProjects = currentProjects.map((p) =>
      map.has(p.id) ? map.get(p.id) : p
    );

    applyProjectFilter();
  };

  // ------- 从收藏夹打开项目列表视图 -------

  window.caseLibOpenCollection = async function (
    collectionId,
    collectionName,
    visibility
  ) {
    if (!collectionId) return;

    try {
      const res = await fetch(`/api/collections/${collectionId}`);
      if (!res.ok) {
        throw new Error("加载收藏夹失败，status=" + res.status);
      }
      const data = await res.json();
      const items = Array.isArray(data.items) ? data.items : [];

      // 把后端返回的 CollectionDetail.items（ProjectMini）
      // 映射成项目卡片需要的结构
      const mapped = items.map((p) => {
        const coverUrl = p.cover_rel_path
          ? `/thumbs/${p.cover_rel_path}`
          : null;
        return {
          id: p.id,
          name: p.name,
          folder_path: p.folder_path,
          fs_path: p.fs_path,
          cover_url: coverUrl,
          architect: p.architect,
          location: null,
          category: null,
          year: null,
          display_order: 0,
        };
      });

      // 标记当前处于“收藏夹视图”
      activeCollectionFilter = {
        id: collectionId,
        name: collectionName || "",
        visibility: visibility || "",
      };

      // 记录最近打开的收藏夹
      try {
        window.localStorage.setItem(
          LAST_COLLECTION_KEY,
          JSON.stringify(activeCollectionFilter)
        );
      } catch (e) {
        console.warn("保存最近收藏夹失败：", e);
      }

      // 通知 Favorites 高亮 banner / 进入收藏夹模式
      if (
        window.Favorites &&
        typeof window.Favorites.ensureCollectionActive === "function"
      ) {
        window.Favorites.ensureCollectionActive(
          collectionId,
          visibility || ""
        );
      }

      // 切换到“按项目”Tab
      setActiveTab("projects");

      // 清空搜索条件，只在此收藏夹范围内展示
      if (searchInput) {
        searchInput.value = "";
        updateSearchClearVisibility();
      }

      // 关闭分页加载，只用这一批项目
      allProjects = mapped;
      currentProjects = mapped.slice();

      // 关闭无限加载
      projectPaging.offset = mapped.length;
      projectPaging.hasMore = false;
      projectPaging.loading = false;

      projectsScrollY = 0;
      window.scrollTo(0, 0);

      renderProjects();
      updateCollectionBanner();

      if (collectionName) {
        showToast(`已打开收藏夹：${collectionName}`);
      } else {
        showToast(`已打开收藏夹 #${collectionId}`);
      }
    } catch (e) {
      console.error("打开收藏夹失败：", e);
      showToast("打开收藏夹失败");
    }
  };

  // ------- 图片分页 -------

  async function fetchImagesPage(options) {
    const opts = options || {};
    const reset = !!opts.reset;
    const query =
      typeof opts.query === "string" ? opts.query.trim() : undefined;
    const projectId =
      typeof opts.projectId === "number" ? opts.projectId : undefined;

    if (imageState.loading) return;

    if (reset) {
      imageState.items = [];
      imageState.offset = 0;
      imageState.hasMore = true;
      imageState.activeQuery = query || "";
      imageState.activeProjectId = projectId != null ? projectId : null;
      resetWaterfallLayout();
    } else {
      if (!imageState.hasMore) return;
    }

    imageState.loading = true;

    try {
      const params = new URLSearchParams();
      params.set("limit", String(imageState.limit));
      params.set("offset", String(imageState.offset));
      if (imageState.activeQuery) {
        params.set("q", imageState.activeQuery);
      }
      if (imageState.activeProjectId != null) {
        params.set("project_id", String(imageState.activeProjectId));
      }

      const url = "/api/images?" + params.toString();
      console.log("fetchImagesPage ->", url);

      const res = await fetch(url);
      if (!res.ok) throw new Error("请求图片列表失败，status=" + res.status);

      const data = await res.json();
      console.log("DEBUG /api/images 返回：", data);

      let pageItems = [];
      if (Array.isArray(data)) {
        pageItems = data;
      } else if (Array.isArray(data.items)) {
        pageItems = data.items;
      } else if (Array.isArray(data.results)) {
        pageItems = data.results;
      } else {
        console.error("图片列表返回结构不是数组：", data);
      }

      const startIndex = imageState.items.length;
      imageState.items = imageState.items.concat(pageItems);
      imageState.offset += pageItems.length;

      if (pageItems.length < imageState.limit) {
        imageState.hasMore = false;
      }

      if (pageItems.length === 0 && startIndex === 0) {
        if (waterfallContainer) {
          waterfallContainer.innerHTML =
            '<p class="center-hint">暂无图片。</p>';
        }
      } else {
        appendImages(pageItems, startIndex);
      }
    } catch (err) {
      console.error("fetchImagesPage 出错：", err);
      if (waterfallContainer) {
        waterfallContainer.innerHTML =
          '<p class="center-hint" style="color:#c00;">加载图片失败，请查看浏览器控制台日志。</p>';
      }
    } finally {
      imageState.loading = false;
    }
  }

  // ------- 只追加图片到列中（不会清空旧的） -------

  function appendImages(images, startIndex) {
    if (!waterfallContainer) return;
    if (!images || images.length === 0) return;

    if (!waterfallCols.length || waterfallColCount <= 0) {
      resetWaterfallLayout();
    }

    images.forEach((img, idx) => {
      const globalIndex = startIndex + idx;

      const item = document.createElement("div");
      item.className = "waterfall-item";
      item.dataset.index = String(globalIndex);

      const imgEl = document.createElement("img");
      imgEl.src = img.thumb_url || img.url;
      imgEl.alt = img.file_name || "";

      item.appendChild(imgEl);

      const colIndex = globalIndex % waterfallColCount;
      const col = waterfallCols[colIndex] || waterfallCols[0];
      col.appendChild(item);
    });

    console.log(
      "追加图片数：",
      images.length,
      "当前总数：",
      imageState.items.length
    );
  }

  // ------- Lightbox 逻辑（缩放 + 拖动 + 设为封面） -------

  function openLightbox(index) {
    if (!lightboxOverlay || !lightboxImg) return;
    const img = imageState.items[index];
    if (!img) return;

    lightboxState.isOpen = true;
    lightboxState.currentIndex = index;
    lightboxState.scale = 1;
    lightboxState.translateX = 0;
    lightboxState.translateY = 0;
    updateLightboxImage();
    lightboxOverlay.classList.add("active");
  }

  function closeLightbox() {
    if (!lightboxOverlay) return;
    lightboxState.isOpen = false;
    lightboxOverlay.classList.remove("active");
    lightboxState.scale = 1;
    lightboxState.translateX = 0;
    lightboxState.translateY = 0;
    updateLightboxImage();
  }

  function updateLightboxImage() {
    if (!lightboxImg) return;
    const img = imageState.items[lightboxState.currentIndex];
    if (!img) return;

    lightboxImg.src = img.url;
    lightboxImg.alt = img.file_name || "";
    const scale = lightboxState.scale || 1;
    const tx = lightboxState.translateX || 0;
    const ty = lightboxState.translateY || 0;
    lightboxImg.style.transform =
      "translate(" + tx + "px, " + ty + "px) scale(" + scale + ")";
  }

  function showRelativeImage(delta) {
    if (!imageState.items.length) return;
    let newIndex = lightboxState.currentIndex + delta;
    if (newIndex < 0) newIndex = imageState.items.length - 1;
    if (newIndex >= imageState.items.length) newIndex = 0;
    lightboxState.currentIndex = newIndex;
    lightboxState.scale = 1;
    lightboxState.translateX = 0;
    lightboxState.translateY = 0;
    updateLightboxImage();
  }

  function extractFileRelPathFromUrl(url) {
    if (!url || typeof url !== "string") return null;
    const qIndex = url.indexOf("?");
    if (qIndex >= 0) {
      url = url.slice(0, qIndex);
    }
    if (url.startsWith("/media/")) {
      return url.slice("/media/".length);
    }
    if (url.startsWith("/thumbs/")) {
      return url.slice("/thumbs/".length);
    }
    const mediaIdx = url.indexOf("/media/");
    if (mediaIdx >= 0) {
      return url.slice(mediaIdx + "/media/".length);
    }
    const thumbsIdx = url.indexOf("/thumbs/");
    if (thumbsIdx >= 0) {
      return url.slice(thumbsIdx + "/thumbs/".length);
    }
    return null;
  }

  async function setCoverForCurrentImage() {
    const img = imageState.items[lightboxState.currentIndex];
    if (!img) return;

    const projectId =
      typeof img.project_id === "number"
        ? img.project_id
        : imageState.activeProjectId;

    if (!projectId) {
      showToast("无法确定项目，不能设为封面");
      return;
    }

    const fileRelPath = extractFileRelPathFromUrl(
      img.url || img.thumb_url || ""
    );
    if (!fileRelPath) {
      showToast("无法解析图片路径");
      return;
    }

    try {
      const res = await fetch(`/api/projects/${projectId}/cover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_rel_path: fileRelPath }),
      });
      if (!res.ok) {
        throw new Error("设为封面请求失败，status=" + res.status);
      }
      const updated = await res.json();
      if (
        window.caseLibOnProjectUpdated &&
        typeof window.caseLibOnProjectUpdated === "function"
      ) {
        window.caseLibOnProjectUpdated(updated);
      }
      showToast("封面已更新");
    } catch (e) {
      console.error("设为封面失败：", e);
      showToast("设为封面失败");
    }
  }

  // 点击瀑布流图片打开大图
  if (waterfallContainer) {
    waterfallContainer.addEventListener("click", (e) => {
      const itemEl = e.target.closest(".waterfall-item");
      if (!itemEl || !waterfallContainer.contains(itemEl)) return;

      const idxStr = itemEl.dataset.index;
      const idx = parseInt(idxStr, 10);
      if (Number.isNaN(idx)) return;

      openLightbox(idx);
    });
  }

  function createLightbox() {
    const overlay = document.createElement("div");
    overlay.className = "lightbox-overlay";

    const inner = document.createElement("div");
    inner.className = "lightbox-inner";

    const imgWrap = document.createElement("div");
    imgWrap.className = "lightbox-img-wrap";

    const imgEl = document.createElement("img");
    imgEl.className = "lightbox-image";

    imgWrap.appendChild(imgEl);

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "lightbox-nav-btn lightbox-nav-prev";
    prevBtn.textContent = "‹";

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "lightbox-nav-btn lightbox-nav-next";
    nextBtn.textContent = "›";

    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "lightbox-close-btn";
    closeBtn.textContent = "×";

    const setCoverBtn = document.createElement("button");
    setCoverBtn.type = "button";
    setCoverBtn.className = "lightbox-set-cover-btn";
    setCoverBtn.textContent = "设为封面";

    // 底部 footer，用来居中“设为封面”按钮
    const footer = document.createElement("div");
    footer.className = "lightbox-footer";
    footer.appendChild(setCoverBtn);

    inner.appendChild(prevBtn);
    inner.appendChild(imgWrap);
    inner.appendChild(nextBtn);
    inner.appendChild(closeBtn);
    inner.appendChild(footer);
    overlay.appendChild(inner);
    document.body.appendChild(overlay);

    lightboxOverlay = overlay;
    lightboxImg = imgEl;
    lightboxImgWrap = imgWrap;
    lightboxSetCoverBtn = setCoverBtn;

    // 点击遮罩空白处关闭
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) {
        closeLightbox();
      }
    });

    // 点击 X 关闭
    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      closeLightbox();
    });

    // 上一张 / 下一张
    prevBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      showRelativeImage(-1);
    });

    nextBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      showRelativeImage(1);
    });

    // 设为封面
    setCoverBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      setCoverForCurrentImage();
    });

    // 键盘：Esc 关闭，左右方向键切换
    window.addEventListener("keydown", (e) => {
      if (!lightboxState.isOpen) return;
      if (e.key === "Escape") {
        closeLightbox();
      } else if (e.key === "ArrowLeft") {
        showRelativeImage(-1);
      } else if (e.key === "ArrowRight") {
        showRelativeImage(1);
      }
    });

    // 滚轮缩放
    imgWrap.addEventListener(
      "wheel",
      (e) => {
        if (!lightboxState.isOpen) return;
        e.preventDefault();

        const zoomFactor = 0.12;
        if (e.deltaY < 0) {
          lightboxState.scale *= 1 + zoomFactor;
        } else {
          lightboxState.scale *= 1 - zoomFactor;
        }
        if (lightboxState.scale < 0.2) lightboxState.scale = 0.2;
        if (lightboxState.scale > 5) lightboxState.scale = 5;

        updateLightboxImage();
      },
      { passive: false }
    );

    // 鼠标拖动查看放大后的细节
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;
    let originX = 0;
    let originY = 0;

    imgWrap.addEventListener("mousedown", (e) => {
      if (!lightboxState.isOpen) return;
      e.preventDefault();
      isDragging = true;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      originX = lightboxState.translateX || 0;
      originY = lightboxState.translateY || 0;
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      e.preventDefault();
      const dx = e.clientX - dragStartX;
      const dy = e.clientY - dragStartY;
      lightboxState.translateX = originX + dx;
      lightboxState.translateY = originY + dy;
      updateLightboxImage();
    });

    window.addEventListener("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
    });
  }

  // ------- 回到顶部按钮 -------

  if (backToTopBtn) {
    backToTopBtn.addEventListener("click", () => {
      window.scrollTo({
        top: 0,
        behavior: "smooth",
      });
    });
  }

  // ------- 滚动事件：header 阴影 + 回到顶部 + 无限加载 -------

  function handleScroll() {
    const scrollY =
      window.scrollY || document.documentElement.scrollTop || 0;

    if (appHeader) {
      if (scrollY > 0) {
        appHeader.classList.add("stuck");
      } else {
        appHeader.classList.remove("stuck");
      }
    }

    if (backToTopBtn) {
      if (scrollY > 200) {
        backToTopBtn.classList.add("show");
      } else {
        backToTopBtn.classList.remove("show");
      }
    }

    const scrollBottom = window.innerHeight + scrollY;
    const docHeight = document.documentElement.scrollHeight;

    if (activeTab === "waterfall") {
      if (!imageState.hasMore || imageState.loading) return;
      if (docHeight - scrollBottom < 400) {
        fetchImagesPage();
      }
    } else if (activeTab === "projects") {
      if (!projectPaging.hasMore || projectPaging.loading) return;
      if (docHeight - scrollBottom < 400) {
        fetchProjects(false);
      }
    }
  }

  window.addEventListener("scroll", handleScroll);

  // ------- 浏览器返回 / 前进：在项目 / 瀑布之间切换 -------

  function handlePopState(event) {
    const state = event.state || {};
    if (!state || !state.view) return;

    if (state.view === "projects") {
      setActiveTab("projects");
      projectsScrollY = state.projectsScrollY || 0;
      setTimeout(() => {
        window.scrollTo(0, projectsScrollY);
      }, 0);
    } else if (state.view === "waterfall") {
      setActiveTab("waterfall");
      const pid =
        typeof state.projectId === "number" ? state.projectId : null;
      fetchImagesPage({
        reset: true,
        projectId: pid != null ? pid : undefined,
      });
      window.scrollTo(0, 0);
    }
  }

  window.addEventListener("popstate", handlePopState);

  // ------- 搜索相关 -------

  if (searchBtn && searchInput) {
    searchBtn.addEventListener("click", () => {
      const q = searchInput.value || "";
      console.log("点击搜索，当前 tab =", activeTab, "关键词 =", q);
      updateSearchClearVisibility();

      if (activeTab === "projects") {
        applyProjectFilter();
      } else {
        fetchImagesPage({ reset: true, query: q });
      }

      if (q.trim()) {
        // 调用后端记录一次全站搜索
        recordSearchKeyword(q);
        // 再异步刷新一次热词栏
        loadHotKeywordsFromServer();
      }
    });

    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        searchBtn.click();
      }
    });

    const handleSearchInputChanged = debounce(() => {
      updateSearchClearVisibility();
      const q = searchInput.value || "";
      if (activeTab === "projects") {
        applyProjectFilter();
      } else {
        fetchImagesPage({ reset: true, query: q });
      }
    }, 300);

    searchInput.addEventListener("input", handleSearchInputChanged);
  }

  if (searchClearBtn && searchInput) {
    searchClearBtn.addEventListener("click", () => {
      searchInput.value = "";
      updateSearchClearVisibility();
      if (activeTab === "projects") {
        applyProjectFilter();
      } else {
        fetchImagesPage({ reset: true, query: "" });
      }
      searchInput.focus();
    });
  }

  // ------- 排序选择 -------

  if (sortSelect) {
    sortSelect.addEventListener("change", () => {
      currentSort = sortSelect.value || "heat";
      // 切换排序时，从第一页重新加载项目列表
      projectsScrollY = 0;
      setActiveTab("projects");
      fetchProjects(true);
      window.scrollTo(0, 0);
    });
  }

  // ------- 刷新案例库（手动 resync） -------

  if (refreshProjectsBtn) {
    refreshProjectsBtn.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/admin/resync", { method: "POST" });
        if (!res.ok) {
          throw new Error("resync 失败，status=" + res.status);
        }

        if (searchInput) {
          searchInput.value = "";
        }
        updateSearchClearVisibility();

        showToast("案例库已刷新");
        await fetchProjects(true);
      } catch (e) {
        console.error("刷新案例库失败：", e);
        showToast("刷新失败");
      }
    });
  }

  // ------- Tab 按钮点击 -------

  if (projectsTabBtn) {
    projectsTabBtn.addEventListener("click", () => {
      try {
        const state = window.history && window.history.state;
        if (state && state.view === "waterfall") {
          window.history.back();
          return;
        }
      } catch (e) { }

      setActiveTab("projects");
      setTimeout(() => {
        window.scrollTo(0, projectsScrollY || 0);
      }, 0);
    });
  }

  if (openImportBtn) {
    openImportBtn.addEventListener("click", () => {
      window.location.href = "/web-import";
    });
  }

  if (waterfallTabBtn) {
    waterfallTabBtn.addEventListener("click", () => {
      projectsScrollY = window.scrollY || 0;
      setActiveTab("waterfall");
      fetchImagesPage({ reset: true });
      window.scrollTo(0, 0);
    });
  }

  if (toggleEditModeBtn) {
    toggleEditModeBtn.addEventListener("click", () => {
      setEditMode(!editMode);
    });
  }

  // ------- 初始化 -------

  // 页面一进来先渲染一遍（此时只有固定标签，等配置和热词加载后会自动更新）
  renderTagStrip();

  createLightbox();
  setActiveTab("projects");
  setEditMode(false);

  // 创建右上角大五角星按钮：挂在工具栏中，用绝对定位浮在编辑按钮上方
  if (toolbarEl) {
    toolbarEl.style.position = toolbarEl.style.position || "relative";

    let bigFavBtn = document.getElementById("big-fav-btn");
    if (!bigFavBtn) {
      bigFavBtn = document.createElement("button");
      bigFavBtn.type = "button";
      bigFavBtn.id = "big-fav-btn";
      bigFavBtn.textContent = "★";
      toolbarEl.appendChild(bigFavBtn);
    }

    bigFavBtn.addEventListener("click", () => {
      if (!window.Favorites) {
        showToast("收藏夹模块尚未加载");
        return;
      }
      const fav = window.Favorites;
      const state =
        typeof fav.getState === "function" ? fav.getState() : null;

      // 如果已经在收藏夹模式，再点一次就退出
      if (state && state.isFavoritesMode) {
        if (typeof fav.exitFavoritesMode === "function") {
          fav.exitFavoritesMode();
        }
        return;
      }

      // 读取最近一次打开的收藏夹
      let last = null;
      try {
        const raw = window.localStorage.getItem(LAST_COLLECTION_KEY);
        if (raw) last = JSON.parse(raw);
      } catch (e) {
        console.warn("读取最近收藏夹失败：", e);
      }

      ensureCollectionBanner();

      if (last && last.id) {
        // 有记录：直接打开上一次收藏夹
        if (typeof fav.ensureCollectionActive === "function") {
          fav.ensureCollectionActive(last.id, last.visibility || "");
        }
        if (typeof window.caseLibOpenCollection === "function") {
          window.caseLibOpenCollection(
            last.id,
            last.name || "",
            last.visibility || ""
          );
        }
      } else {
        // 没有记录：只进入收藏夹模式，让用户在 banner 中选择
        if (typeof fav.enterFavoritesMode === "function") {
          fav.enterFavoritesMode();
        } else if (typeof fav.openManager === "function") {
          fav.openManager();
        }
      }
    });
  }

  // 确保收藏夹模块初始化（如果脚本已加载）
  window.addEventListener("load", () => {
    if (
      window.Favorites &&
      typeof window.Favorites.init === "function"
    ) {
      window.Favorites.init();
    }
  });

  updateCollectionBanner();

  try {
    if (window.history && "replaceState" in window.history) {
      const initState = Object.assign({}, window.history.state || {}, {
        view: "projects",
        projectsScrollY: window.scrollY || 0,
      });
      window.history.replaceState(initState, "");
    }
  } catch (e) {
    console.warn("初始化 history state 失败：", e);
  }

  // 先加载前端配置，再拉取首页项目
  (async () => {
    await loadFrontendConfig();
    await fetchProjects(true);
  })();
})();
