// favorites.js
(function () {
  const state = {
    // 后端收藏夹 API 根路径（固定）
    apiBase: "/api/collections",

    // 弹窗相关
    overlayEl: null,
    dialogEl: null,
    listEl: null,
    tabPrivateBtn: null,
    tabPublicBtn: null,
    currentProjectId: null, // 有值 = 给某个项目选择收藏夹；null = 管理模式
    currentTab: "private", // 'private' | 'public'
    collections: {
      private: [],
      public: [],
    },
    membership: {
      private: new Set(), // 当前项目在哪些 private 收藏夹里
      public: new Set(), // 当前项目在哪些 public 收藏夹里
    },
    isLoading: false,

    // 收藏夹模式（右上角大星星 + banner）
    bigFavBtnEl: null,
    bannerEl: null,
    bannerLeftEl: null,
    isFavoritesMode: false,
    allCollections: [],
    activeCollectionId: null,
    sortFrozen: false, // 是否冻结当前排序
    renderOrder: [],

  };

  // ===== 工具函数 =====

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function createEl(tag, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  function showOverlay() {
    if (!state.overlayEl) return;
    state.overlayEl.classList.add("fav-overlay--visible");
  }

  function hideOverlay() {
    if (!state.overlayEl) return;
    state.overlayEl.classList.remove("fav-overlay--visible");
    state.currentProjectId = null;
    state.membership.private = new Set();
    state.membership.public = new Set();
    state.renderOrder = [];

  }

  // 只控制“加载中…”小字和列表显隐，不再删掉列表 DOM
  function setLoading(isLoading) {
    state.isLoading = isLoading;
    if (!state.dialogEl) return;
    const body = $(".fav-dialog-body", state.dialogEl);
    if (!body) return;

    let loadingEl = $(".fav-dialog-loading", body);
    let listEl = $(".fav-collection-list", body);

    if (isLoading) {
      if (!loadingEl) {
        loadingEl = createEl("div", "fav-dialog-loading");
        loadingEl.textContent = "加载中…";
        body.appendChild(loadingEl);
      }
      if (listEl) listEl.style.display = "none";
      loadingEl.style.display = "flex";
    } else {
      if (loadingEl) loadingEl.style.display = "none";
      if (listEl) listEl.style.display = "";
    }
  }

  function requestJSON(url, options) {
    return fetch(url, options).then(function (res) {
      if (!res.ok) {
        return res
          .json()
          .catch(function () {
            throw new Error("HTTP " + res.status);
          })
          .then(function (data) {
            throw new Error(data.detail || "HTTP " + res.status);
          });
      }
  
      // 没内容
      if (res.status === 204) return null;
  
      // ✅ 不直接用 res.json()，先读 text，空串就返回 null
      return res.text().then(function (txt) {
        if (!txt) return null;
        try {
          return JSON.parse(txt);
        } catch (e) {
          console.warn("解析 JSON 失败：", e);
          return null;
        }
      });
    });
  }
  
  // ===== 收藏夹模式：右上角大星星 + banner =====

  // 高亮指定 id 的 banner 标签
  function setActiveBannerTagById(collectionId) {
    if (!state.bannerEl || !collectionId) return false;
    const tags = state.bannerEl.querySelectorAll(".collection-banner-tag");
    let hit = false;
    for (let i = 0; i < tags.length; i++) {
      const tag = tags[i];
      const cidStr = tag.getAttribute("data-collection-id");
      const cid = cidStr ? parseInt(cidStr, 10) : NaN;
      if (cid && cid === collectionId) {
        tag.classList.add("active");
        hit = true;
      } else {
        tag.classList.remove("active");
      }
    }
    return hit;
  }

  // 初始化收藏夹模式相关 DOM（只做一次）
  function ensureFavoritesModeUI() {
    if (!state.bigFavBtnEl) {
      state.bigFavBtnEl = document.getElementById("big-fav-btn");
    }

    if (!state.bannerEl) {
      var banner = document.getElementById("collection-banner");
      if (banner) {
        // 重建 banner 内部结构：左侧标签容器 + 右侧退出按钮
        banner.innerHTML = "";

        var left = createEl("div", "collection-banner-left");

        var exitBtn = createEl("button", "collection-banner-btn");
        exitBtn.type = "button";
        exitBtn.textContent = "退出收藏夹";
        exitBtn.setAttribute("data-fav-banner-action", "exit");

        banner.appendChild(left);
        banner.appendChild(exitBtn);

        // 默认隐藏，进入收藏夹模式时再显示
        banner.style.display = "none";

        state.bannerEl = banner;
        state.bannerLeftEl = left;
      }
    }

    // 注意：大星星的点击事件由 app.js 绑定，这里不再绑 click
  }

  // 进入收藏夹模式（仅控制 UI，不决定打开哪个收藏夹）
  function enterFavoritesMode() {
    ensureFavoritesModeUI();
    state.isFavoritesMode = true;

    if (state.bigFavBtnEl) {
      state.bigFavBtnEl.classList.add("is-active");
    }
    if (state.bannerEl) {
      state.bannerEl.style.display = "flex";
    }

    // 拉取所有收藏夹，用于 banner 标签
    if (!state.allCollections || state.allCollections.length === 0) {
      loadAllCollections();
    } else {
      renderBannerCollections();
      if (state.activeCollectionId) {
        setActiveBannerTagById(state.activeCollectionId);
      }
    }

    if (
      window.caseLibOnEnterFavoritesMode &&
      typeof window.caseLibOnEnterFavoritesMode === "function"
    ) {
      window.caseLibOnEnterFavoritesMode();
    }
  }

  // 让某个收藏夹在 banner 中高亮（给 app.js 用）
  function ensureCollectionActive(collectionId, visibility) {
    if (!collectionId) return;
    ensureFavoritesModeUI();
    state.activeCollectionId = collectionId;

    if (!state.isFavoritesMode) {
      enterFavoritesMode();
      return;
    }

    if (state.bannerEl) {
      state.bannerEl.style.display = "flex";
    }

    if (state.allCollections && state.allCollections.length > 0) {
      setActiveBannerTagById(collectionId);
    } else {
      loadAllCollections();
    }
  }

  // 退出收藏夹模式（回到全站项目列表，真正的项目刷新交给 app.js）
  function exitFavoritesMode() {
    state.isFavoritesMode = false;
    state.activeCollectionId = null;

    if (state.bigFavBtnEl) {
      state.bigFavBtnEl.classList.remove("is-active");
    }
    if (state.bannerEl) {
      state.bannerEl.style.display = "none";
    }

    if (
      window.caseLibOnExitFavoritesMode &&
      typeof window.caseLibOnExitFavoritesMode === "function"
    ) {
      window.caseLibOnExitFavoritesMode();
    }
  }

  // 调用 /api/collections/all，获取所有收藏夹
  function loadAllCollections() {
    var url = state.apiBase + "/all";
    return requestJSON(url)
      .then(function (data) {
        state.allCollections = data || [];
        renderBannerCollections();
        if (state.activeCollectionId) {
          setActiveBannerTagById(state.activeCollectionId);
        }
      })
      .catch(function (err) {
        console.error("加载所有收藏夹失败:", err);
        if (state.bannerLeftEl) {
          state.bannerLeftEl.innerHTML =
            '<span class="fav-error">加载收藏夹失败：' +
            (err.message || "未知错误") +
            "</span>";
        }
      });
  }

  // 在 banner 上渲染收藏夹标签（带类型信息）
  // 在 banner 上渲染收藏夹标签：图标 + 名称 + 创建人
  function renderBannerCollections() {
    if (!state.bannerLeftEl) return;
    var cols = state.allCollections || [];
    
    // ★ 过滤掉「不是我创建的私人收藏夹」
    cols = cols.filter(function (c) {
      if (c.visibility === "private" && !c.owner_is_me) {
        return false;
      }
      return true;
    });

    if (!cols.length) {
      state.bannerLeftEl.innerHTML =
        '<span class="fav-empty">暂无收藏夹，可以先在项目卡片上使用星标创建。</span>';
      return;
    }

    var frag = document.createDocumentFragment();

    cols.forEach(function (c) {
      var tag = createEl("span", "collection-banner-tag");
      tag.setAttribute("data-collection-id", String(c.id));
      tag.setAttribute("data-visibility", c.visibility || "");
      tag.setAttribute("data-owner-is-me", c.owner_is_me ? "1" : "0");
      if (c.owner_name) {
        tag.setAttribute("data-owner-name", c.owner_name);
      }

      // 图标：👤 私人 / 👥 公共
      var icon = createEl("span", "collection-banner-icon");
      icon.textContent = c.visibility === "public" ? "👥" : "👤";

      // 名称
      var nameSpan = createEl("span", "collection-banner-name");
      nameSpan.textContent = c.name || "";

      tag.appendChild(icon);
      tag.appendChild(nameSpan);

      // 创建人（如果后端有 owner_name）
      if (c.owner_name) {
        var ownerSpan = createEl("span", "collection-banner-owner");
        ownerSpan.textContent = c.owner_name;
        tag.appendChild(ownerSpan);
      }

      frag.appendChild(tag);
    });

    state.bannerLeftEl.innerHTML = "";
    state.bannerLeftEl.appendChild(frag);
  }
  

  // ===== DOM 结构：对话框（弹窗） =====

  function ensureDialog() {
    if (state.overlayEl && state.dialogEl) return;

    const overlay = createEl("div", "fav-overlay");
    const dialog = createEl("div", "fav-dialog");

    // header
    const header = createEl("div", "fav-dialog-header");

    const tabs = createEl("div", "fav-tabs");
    const tabPrivate = createEl("button", "fav-tab fav-tab--active");
    tabPrivate.type = "button";
    tabPrivate.textContent = "私人收藏夹";
    tabPrivate.setAttribute("data-fav-tab", "private");

    const tabPublic = createEl("button", "fav-tab");
    tabPublic.type = "button";
    tabPublic.textContent = "公共收藏夹";
    tabPublic.setAttribute("data-fav-tab", "public");

    tabs.appendChild(tabPrivate);
    tabs.appendChild(tabPublic);

    const closeBtn = createEl("button", "fav-dialog-close");
    closeBtn.type = "button";
    closeBtn.textContent = "×";

    header.appendChild(tabs);
    header.appendChild(closeBtn);

    // body
    const body = createEl("div", "fav-dialog-body");
    const list = createEl("div", "fav-collection-list");
    body.appendChild(list);

    // footer
    const footer = createEl("div", "fav-dialog-footer");
    const createBtn = createEl("button", "fav-create-btn");
    createBtn.type = "button";
    createBtn.textContent = "＋ 新建收藏夹";
    footer.appendChild(createBtn);

    dialog.appendChild(header);
    dialog.appendChild(body);
    dialog.appendChild(footer);

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    state.overlayEl = overlay;
    state.dialogEl = dialog;
    state.listEl = list;
    state.tabPrivateBtn = tabPrivate;
    state.tabPublicBtn = tabPublic;
  }

  // ===== 渲染收藏夹列表（弹窗内） =====
  // ===== 渲染收藏夹列表（弹窗内） =====

  // 帮助函数：把 private / public 两个数组合并并排序
  function getSortedCollections() {
    var priv = Array.isArray(state.collections.private)
      ? state.collections.private.slice()
      : [];
    var pub = Array.isArray(state.collections.public)
      ? state.collections.public.slice()
      : [];

    // 排序规则：先按「私密在上、公开在下」，再按最近更新时间 / 创建时间，从新到旧
    function getTime(c) {
      var t =
        (c && c.updated_at) ||
        (c && c.last_item_at) ||
        (c && c.created_at) ||
        null;
      if (!t) return 0;
      var ts = Date.parse(t);
      return isNaN(ts) ? 0 : ts;
    }

    priv.sort(function (a, b) {
      var tb = getTime(b);
      var ta = getTime(a);
      if (tb !== ta) return tb - ta;
      return (b.id || 0) - (a.id || 0);
    });

    pub.sort(function (a, b) {
      var tb = getTime(b);
      var ta = getTime(a);
      if (tb !== ta) return tb - ta;
      return (b.id || 0) - (a.id || 0);
    });

    return priv.concat(pub);
  }

  function findCollectionById(collectionId) {
    var idNum = typeof collectionId === "number"
      ? collectionId
      : parseInt(collectionId, 10);
    if (!idNum || isNaN(idNum)) return null;
  
    function sameId(c) {
      return parseInt(c.id, 10) === idNum;
    }
  
    var priv = Array.isArray(state.collections.private)
      ? state.collections.private
      : [];
    var pub = Array.isArray(state.collections.public)
      ? state.collections.public
      : [];
  
    for (var i = 0; i < priv.length; i++) {
      if (sameId(priv[i])) return priv[i];
    }
    for (var j = 0; j < pub.length; j++) {
      if (sameId(pub[j])) return pub[j];
    }
    return null;
  }
  
  function renderCollections() {
    if (!state.listEl) return;
    var isAssignMode = !!state.currentProjectId;
  
    // ========== 1) 第一次：初始化 renderOrder ==========
    if (!Array.isArray(state.renderOrder) || state.renderOrder.length === 0) {
      // 用原来的排序规则算出「初始顺序」
      var initial = getSortedCollections(); // 还是：私密在上 + 最近使用在前
      state.renderOrder = initial.map(function (c) {
        return c.id;
      });
    }
  
    if (!state.renderOrder.length) {
      state.listEl.innerHTML =
        '<div class="fav-empty">暂无收藏夹，点击下方“新建收藏夹”创建一个。</div>';
      return;
    }
  
    // 记住滚动条位置
    var prevScrollTop = state.listEl.scrollTop || 0;
  
    var frag = document.createDocumentFragment();
    var any = false;
  
    // ========== 2) 严格按 renderOrder 的顺序画 ==========
    state.renderOrder.forEach(function (id) {
      var c = findCollectionById(id);
      if (!c) return;
      any = true;
  
      var rawVis = (c && c.visibility) || "private";
      var visibility =
        rawVis === "public" || rawVis === "PUBLIC" ? "public" : "private";
      var membershipSet = state.membership[visibility];
      var included =
        isAssignMode &&
        membershipSet &&
        typeof c.id !== "undefined" &&
        membershipSet.has(c.id);
  
      var row = createEl("div", "fav-collection-row");
      row.setAttribute("data-collection-id", String(c.id));
      row.setAttribute("data-visibility", visibility);
      row.setAttribute("data-name", c.name || "");
      row.setAttribute("data-owner-is-me", c.owner_is_me ? "1" : "0");
  
      // 私人 / 公共底色
      row.classList.add(
        visibility === "public"
          ? "fav-collection-row--public"
          : "fav-collection-row--private"
      );
  
      if (included) {
        row.classList.add("fav-collection-row--selected");
      }
      if (c.owner_is_me) {
        row.classList.add("fav-collection-row--mine");
      }
  
      // 主体：名称 + meta
      var main = createEl("div", "fav-collection-row-main");
  
      var nameEl = createEl("div", "fav-collection-name");
      nameEl.textContent = c.name || "(未命名收藏夹)";
      main.appendChild(nameEl);
  
      var meta = createEl("div", "fav-collection-meta");
  
      var countSpan = createEl("span", "fav-collection-count");
      countSpan.textContent = (c.item_count || 0) + " 个项目";
      meta.appendChild(countSpan);
  
      if (c.owner_name) {
        var ownerSpan = createEl("span", "fav-collection-owner");
        ownerSpan.textContent = c.owner_name;
        meta.appendChild(ownerSpan);
      }
  
      main.appendChild(meta);
      row.appendChild(main);
  
      // 右侧容器
      var rightBox = createEl("div", "fav-collection-right");
  
      // ① 选项目模式：显示 “＋加入 / ✔已包含”
      if (isAssignMode) {
        var toggleEl = createEl("div", "fav-collection-toggle");
        toggleEl.textContent = included ? "✔ 已包含" : "＋ 加入";
        rightBox.appendChild(toggleEl);
      }
  
      // ② 查看 / 重命名 / 删除
      var actions = createEl("div", "fav-collection-actions");
  
      var openBtn = createEl("button", "fav-action-link");
      openBtn.type = "button";
      openBtn.textContent = "查看";
      openBtn.setAttribute("data-fav-action", "open");
      actions.appendChild(openBtn);
  
      if (c.owner_is_me) {
        var renameBtn = createEl("button", "fav-action-link");
        renameBtn.type = "button";
        renameBtn.textContent = "重命名";
        renameBtn.setAttribute("data-fav-action", "rename");
        actions.appendChild(renameBtn);
  
        var delBtn = createEl(
          "button",
          "fav-action-link fav-action-link--danger"
        );
        delBtn.type = "button";
        delBtn.textContent = "删除";
        delBtn.setAttribute("data-fav-action", "delete");
        actions.appendChild(delBtn);
      }
  
      rightBox.appendChild(actions);
  
      // ③ 私密/公开开关
      if (c.owner_is_me) {
        var visLabel = createEl("span", "fav-vis-label");
        visLabel.textContent = "设为私密";
        actions.appendChild(visLabel);
  
        var visBtn = createEl("button", "fav-vis-toggle");
        visBtn.type = "button";
        visBtn.setAttribute("data-fav-vis-toggle", "1");
        visBtn.setAttribute("data-collection-id", String(c.id));
  
        var knob = createEl("span", "fav-vis-toggle-knob");
        visBtn.appendChild(knob);
  
        if (visibility === "private") {
          visBtn.classList.add("fav-vis-toggle--on");
        }
  
        actions.appendChild(visBtn);
      } else {
        var visLabelReadOnly = createEl("span", "fav-vis-label");
        visLabelReadOnly.textContent = "设为私密";
        actions.appendChild(visLabelReadOnly);
  
        var visBtnReadOnly = createEl(
          "button",
          "fav-vis-toggle fav-vis-toggle--disabled"
        );
        visBtnReadOnly.type = "button";
        visBtnReadOnly.disabled = true;
  
        var knob2 = createEl("span", "fav-vis-toggle-knob");
        visBtnReadOnly.appendChild(knob2);
  
        if (visibility === "private") {
          visBtnReadOnly.classList.add("fav-vis-toggle--on");
        }
  
        actions.appendChild(visBtnReadOnly);
      }
  
      row.appendChild(rightBox);
      frag.appendChild(row);
    });
  
    if (!any) {
      state.listEl.innerHTML =
        '<div class="fav-empty">暂无收藏夹，点击下方“新建收藏夹”创建一个。</div>';
    } else {
      state.listEl.innerHTML = "";
      state.listEl.appendChild(frag);
      // 恢复滚动位置
      state.listEl.scrollTop = prevScrollTop;
    }
  }
  
  function switchTab(tab) {
    if (tab !== "private" && tab !== "public") return;
    if (!state.tabPrivateBtn || !state.tabPublicBtn) return;
  
    state.currentTab = tab;
    if (tab === "private") {
      state.tabPrivateBtn.classList.add("fav-tab--active");
      state.tabPublicBtn.classList.remove("fav-tab--active");
    } else {
      state.tabPublicBtn.classList.add("fav-tab--active");
      state.tabPrivateBtn.classList.remove("fav-tab--active");
    }
  
    // ★ 不再重新拉接口，只是按当前数据重画
    renderCollections();
  }
  
  // ===== 与后端交互（弹窗） =====

  function loadCollections(visibility) {
    visibility = visibility || state.currentTab || "private";

    var url =
      state.apiBase + "?visibility=" + encodeURIComponent(visibility);
    if (visibility === "public") {
      // 看全部公共收藏夹，mine 不加或为 false 即可
      // url += "&mine=false";
    }

    return requestJSON(url)
      .then(function (data) {
        state.collections[visibility] = data || [];
        // 不在这里 render，让调用方统一调用 renderCollections()
      })
      .catch(function (err) {
        console.error("加载收藏夹失败:", err);
        if (state.listEl) {
          state.listEl.innerHTML =
            '<div class="fav-error">加载收藏夹失败：' +
            (err.message || "未知错误") +
            "</div>";
        }
      });
  }

  function loadMembership(projectId) {
    const url =
      state.apiBase + "/of_project/" + encodeURIComponent(projectId);
    return requestJSON(url)
      .then(function (data) {
        // data.private / data.public 都是 CollectionSummary 数组
        state.membership.private = new Set(
          (data.private || []).map(function (c) {
            return c.id;
          })
        );
        state.membership.public = new Set(
          (data.public || []).map(function (c) {
            return c.id;
          })
        );
      })
      .catch(function (err) {
        console.error("加载项目所属收藏夹失败:", err);
        state.membership.private = new Set();
        state.membership.public = new Set();
      });
  }

  function toggleProjectInCollection(collectionId) {
    var projectId = state.currentProjectId;
    if (!projectId || !collectionId) return;

    var col = findCollectionById(collectionId);
    if (!col) return;

    var visibility = col.visibility === "public" ? "public" : "private";
    var membershipSet = state.membership[visibility];
    if (!membershipSet) {
      membershipSet = new Set();
      state.membership[visibility] = membershipSet;
    }
    var included = membershipSet.has(collectionId);
    
    if (!included) {
      // 添加
      var url = state.apiBase + "/" + collectionId + "/items";
      return requestJSON(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ project_id: projectId }),
      })
        .then(function () {
          membershipSet.add(collectionId);
          updateRowVisual(collectionId, true);
        })
        .catch(function (err) {
          console.error("添加到收藏夹失败:", err);
          alert("添加到收藏夹失败：" + (err.message || "未知错误"));
        });
    } else {
      // 移除
      var urlDel =
        state.apiBase +
        "/" +
        collectionId +
        "/items/" +
        encodeURIComponent(projectId);
      return requestJSON(urlDel, {
        method: "DELETE",
      })
        .then(function () {
          membershipSet.delete(collectionId);
          updateRowVisual(collectionId, false);
        })
        .catch(function (err) {
          console.error("从收藏夹移除失败:", err);
          alert("从收藏夹移除失败：" + (err.message || "未知错误"));
        });
    }
  }

  function updateRowVisual(collectionId, included) {
    if (!state.listEl) return;
    var row = state.listEl.querySelector(
      '.fav-collection-row[data-collection-id="' + collectionId + '"]'
    );
    if (!row) return;
    var toggleEl = $(".fav-collection-toggle", row);
    if (included) {
      row.classList.add("fav-collection-row--selected");
      if (toggleEl) toggleEl.textContent = "✔ 已包含";
    } else {
      row.classList.remove("fav-collection-row--selected");
      if (toggleEl) toggleEl.textContent = "＋ 加入";
    }
  }

  function createCollectionInteractive() {
    var name = window.prompt("请输入收藏夹名称：");
    if (!name) return;
    name = name.trim();
    if (!name) return;
  
    // ★ 默认创建为私人收藏夹
    var visibility = "private";
  
    var url = state.apiBase;
    return requestJSON(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: name,
        visibility: visibility,
      }),
    })
      .then(function (col) {
        // 更新本地缓存（仍按 private / public 两个数组存）
        if (!state.collections.private) state.collections.private = [];
        state.collections.private.unshift(col);
  
        // ★ 新建的收藏夹插到当前弹窗顺序最前面（也可以改成 push 加在最后）
        if (!Array.isArray(state.renderOrder)) {
          state.renderOrder = [];
        }
        state.renderOrder.unshift(col.id);

        // 重新渲染合集列表（现在是合并显示）
        renderCollections();
  
        // 如果当前有项目，自动把这个项目加入新建收藏夹
        if (state.currentProjectId) {
          if (!state.membership.private) {
            state.membership.private = new Set();
          }
          state.membership.private.add(col.id);
  
          var addUrl = state.apiBase + "/" + col.id + "/items";
          return requestJSON(addUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ project_id: state.currentProjectId }),
          }).catch(function (err) {
            console.error("新建收藏夹后添加项目失败:", err);
          });
        }
      })
      .catch(function (err) {
        console.error("新建收藏夹失败:", err);
        alert("新建收藏夹失败：" + (err.message || "未知错误"));
      });
  }

  function toggleCollectionVisibility(collectionId, btnEl) {
    var idNum =
      typeof collectionId === "number"
        ? collectionId
        : parseInt(collectionId, 10);
    if (!idNum || isNaN(idNum)) return;
  
    var col = findCollectionById(idNum);
    if (!col) return;
  
    // 再保险：不是自己建的直接返回
    if (!col.owner_is_me) {
      return;
    }
  
    var oldVis =
      col.visibility === "public" || col.visibility === "PUBLIC"
        ? "public"
        : "private";
    var newVis = oldVis === "public" ? "private" : "public";
  
    var url = state.apiBase + "/" + encodeURIComponent(idNum);
  
    requestJSON(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ visibility: newVis }),
    })
      .then(function () {
        // 1) 切按钮视觉
        if (btnEl) {
          if (newVis === "private") {
            btnEl.classList.add("fav-vis-toggle--on");
          } else {
            btnEl.classList.remove("fav-vis-toggle--on");
          }
        }
  
        // 2) 更新本地对象字段
        col.visibility = newVis;
  
        // 3) 从旧分组数组删掉，放进新分组数组的最后
        ["private", "public"].forEach(function (vis) {
          var list = state.collections[vis];
          if (!Array.isArray(list)) return;
          state.collections[vis] = list.filter(function (c) {
            return parseInt(c.id, 10) !== idNum;
          });
        });
  
        if (!state.collections[newVis]) {
          state.collections[newVis] = [];
        }
        state.collections[newVis].push(col); // 放在该组末尾，不抢到最上面
  
        // 4) 同步 banner 用的 allCollections
        state.allCollections = (state.allCollections || []).map(function (c) {
          if (parseInt(c.id, 10) === idNum) {
            var copy = Object.assign({}, c);
            copy.visibility = newVis;
            return copy;
          }
          return c;
        });
  
        // 5) 用当前顺序重新渲染（因 sortFrozen=true，不会再按时间重排）
        renderCollections();
        renderBannerCollections();
      })
      .catch(function (err) {
        console.error("切换私密 / 公开失败:", err);
        alert("切换私密 / 公开失败：" + (err.message || "未知错误"));
      });
  }
  

  function renameCollectionInteractive(collectionId, oldName) {
    var newName = window.prompt(
      "请输入新的收藏夹名称：",
      oldName || ""
    );
    if (!newName) return;
    newName = newName.trim();
    if (!newName || newName === oldName) return;

    var url = state.apiBase + "/" + encodeURIComponent(collectionId);
    return requestJSON(url, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name: newName }),
    })
      .then(function (updated) {
        ["private", "public"].forEach(function (vis) {
          var list = state.collections[vis];
          if (!Array.isArray(list)) return;
          for (var i = 0; i < list.length; i++) {
            if (list[i].id === updated.id) {
              list[i] = updated;
            }
          }
        });

        // banner 里的 allCollections 也同步
        state.allCollections = (state.allCollections || []).map(function (c) {
          return c.id === updated.id ? updated : c;
        });

        renderCollections();
        renderBannerCollections();
      })
      .catch(function (err) {
        console.error("重命名收藏夹失败:", err);
        alert("重命名收藏夹失败：" + (err.message || "未知错误"));
      });
  }

  function deleteCollectionInteractive(collectionId, name, visibility) {
    var ok = window.confirm(
      "确定要删除收藏夹「" +
        (name || "") +
        "」吗？\n该收藏夹中的项目关系会一并删除，但不会影响项目本身。"
    );
    if (!ok) return;

    var url = state.apiBase + "/" + encodeURIComponent(collectionId);
    return requestJSON(url, {
      method: "DELETE",
    })
    .then(function () {
      ["private", "public"].forEach(function (vis) {
        var list = state.collections[vis];
        if (!Array.isArray(list)) return;
        state.collections[vis] = list.filter(function (c) {
          return c.id !== collectionId;
        });
      });
    
      // ★ 同步 renderOrder
      if (Array.isArray(state.renderOrder) && state.renderOrder.length > 0) {
        state.renderOrder = state.renderOrder.filter(function (id) {
          return id !== collectionId;
        });
      }
    
      // 从 allCollections 中删掉
      state.allCollections = (state.allCollections || []).filter(function (c) {
        return c.id !== collectionId;
      });
    
      if (state.activeCollectionId === collectionId) {
        state.activeCollectionId = null;
      }
    
      renderCollections();
      renderBannerCollections();
    })
    
      .catch(function (err) {
        console.error("删除收藏夹失败:", err);
        alert("删除收藏夹失败：" + (err.message || "未知错误"));
      });
  }

  // ===== 打开 / 关闭对话框 =====

  function openSaveDialog(projectId) {
    if (!projectId) return;
  
    ensureDialog();
    state.currentProjectId = projectId;
  
    showOverlay();
    setLoading(true);
  
    // ★ 每次打开新弹窗：清空 renderOrder，让这次重新算一次初始顺序
    state.renderOrder = [];
  
    // 默认打开私人收藏夹 tab
    state.currentTab = "private";
    if (state.tabPrivateBtn && state.tabPublicBtn) {
      state.tabPrivateBtn.classList.add("fav-tab--active");
      state.tabPublicBtn.classList.remove("fav-tab--active");
    }
  
    // 同时加载收藏夹列表 + 当前项目所属收藏夹
    Promise.all([
      loadCollections("private"),
      loadCollections("public"),
      loadMembership(projectId),
    ])
      .then(function () {
        renderCollections(); // 第一次渲染时会初始化 renderOrder
      })
      .finally(function () {
        setLoading(false);
      });
  }
  
  // 管理模式：不绑定具体项目

  function openManager() {
    ensureDialog();
    state.currentProjectId = null;
    state.membership.private = new Set();
    state.membership.public = new Set();
  
    showOverlay();
    setLoading(true);
  
    // ★ 每次打开管理弹窗：清空 renderOrder
    state.renderOrder = [];
  
    state.currentTab = "private";
    if (state.tabPrivateBtn && state.tabPublicBtn) {
      state.tabPrivateBtn.classList.add("fav-tab--active");
      state.tabPublicBtn.classList.remove("fav-tab--active");
    }
  
    Promise.all([loadCollections("private"), loadCollections("public")])
      .then(function () {
        renderCollections(); // 同样，第一次渲染里初始化 renderOrder
      })
      .finally(function () {
        setLoading(false);
      });
  }
  
  // ===== 事件绑定（事件代理） =====

  function handleDocumentClick(evt) {
    var target = evt.target;

    // A) 收藏夹模式 banner：点击标签
    var bannerTag =
      target.closest && target.closest(".collection-banner-tag");
    if (bannerTag) {
      var cidStr = bannerTag.getAttribute("data-collection-id");
      var cid = cidStr ? parseInt(cidStr, 10) : NaN;
      if (!cid || isNaN(cid)) return;

      var nameNode = bannerTag.querySelector(".collection-banner-name");

      var name = nameNode ? nameNode.textContent : bannerTag.textContent || "";
      var visibility =
        bannerTag.getAttribute("data-visibility") || "";
      
      var ownerIsMe =
      bannerTag.getAttribute("data-owner-is-me") === "1";
  
      // ★ 再防一手：别人私人收藏夹即使出现（比如后端误返回），也不响应点击
      if (visibility === "private" && !ownerIsMe) {
        return;
      }
  
      // 先让本模块记录 & 高亮
      ensureCollectionActive(cid, visibility);

      // 打开对应收藏夹（交给 app.js 实现）
      if (
        window.caseLibOpenCollection &&
        typeof window.caseLibOpenCollection === "function"
      ) {
        window.caseLibOpenCollection(cid, name, visibility);
      }
      return;
    }

    // B) 收藏夹模式 banner：右侧退出按钮
    var bannerExitBtn =
      target.closest &&
      target.closest("[data-fav-banner-action='exit']");
    if (bannerExitBtn) {
      exitFavoritesMode();
      return;
    }

    // 1) 点击卡片上的“收藏”按钮：data-action="open-favorite-dialog"
    var favBtn =
      target.closest &&
      target.closest("[data-action='open-favorite-dialog']");
    if (favBtn) {
      var pidStr = favBtn.getAttribute("data-project-id");
      var pid = pidStr ? parseInt(pidStr, 10) : NaN;
      if (pid && !isNaN(pid)) {
        openSaveDialog(pid);
      }
      return;
    }

    // 之后的逻辑都需要 dialog 存在
    if (!state.overlayEl || !state.dialogEl) return;

    // 2) 点击遮罩关闭
    if (target === state.overlayEl) {
      hideOverlay();
      return;
    }

    // 3) 关闭按钮
    if (target.classList.contains("fav-dialog-close")) {
      hideOverlay();
      return;
    }

    // 4) 切换 tab
    var tabBtn =
      target.closest && target.closest("[data-fav-tab]");
    if (tabBtn) {
      var tab = tabBtn.getAttribute("data-fav-tab");
      switchTab(tab);
      return;
    }

    // 5) 新建收藏夹
    var createBtn =
      target.closest && target.closest(".fav-create-btn");
    if (createBtn) {
      createCollectionInteractive();
      return;
    }
      // 5.5) 点击可见性开关（私密 / 公开）
      var visToggle =
        target.closest && target.closest("[data-fav-vis-toggle='1']");
      if (visToggle) {
        var cidAttr = visToggle.getAttribute("data-collection-id");
        var cid = cidAttr ? parseInt(cidAttr, 10) : NaN;
        if (cid && !isNaN(cid)) {
          // 阻止冒泡到行点击（否则会把项目加入 / 移出）
          evt.stopPropagation();
          toggleCollectionVisibility(cid, visToggle);
        }
        return;
      }
  
    // 6) 点击收藏夹行
        // 6) 点击收藏夹行
      // 6) 点击收藏夹行
    var row =
      target.closest && target.closest(".fav-collection-row");
    if (row && row.getAttribute("data-collection-id")) {
      var cid = parseInt(
        row.getAttribute("data-collection-id"),
        10
      );
      if (!cid || isNaN(cid)) return;

      var name = row.getAttribute("data-name") || "";
      var visibility =
        row.getAttribute("data-visibility") || "";

      // 是否点在操作按钮上
      var actionBtn =
        target.closest && target.closest("[data-fav-action]");
      var action = actionBtn
        ? actionBtn.getAttribute("data-fav-action") || "open"
        : "open";

      // ==== ① “给某个项目选收藏夹”模式 ====
      if (state.currentProjectId) {
        // 如果是点击“查看 / 重命名 / 删除”按钮 → 走管理逻辑，不触发添加/移除
        if (actionBtn) {
          if (action === "open") {
            if (
              window.caseLibOpenCollection &&
              typeof window.caseLibOpenCollection === "function"
            ) {
              window.caseLibOpenCollection(
                cid,
                name,
                visibility
              );
            }
            hideOverlay();
          } else if (action === "rename") {
            renameCollectionInteractive(cid, name);
          } else if (action === "delete") {
            deleteCollectionInteractive(cid, name, visibility);
          }
          return;
        }

        // 不是点在操作按钮 → 视为添加/移除项目
        toggleProjectInCollection(cid);
        return;
      }

      // ==== ② 纯“管理模式” ====
      if (action === "open") {
        if (
          window.caseLibOpenCollection &&
          typeof window.caseLibOpenCollection === "function"
        ) {
          window.caseLibOpenCollection(
            cid,
            name,
            visibility
          );
        }
        hideOverlay();
      } else if (action === "rename") {
        renameCollectionInteractive(cid, name);
      } else if (action === "delete") {
        deleteCollectionInteractive(cid, name, visibility);
      }

      return;
    }


  }

  // ===== 对外暴露的 API =====

  function init() {
    // 只绑定一次全局 click 代理
    if (!window.__favorites_click_bound__) {
      document.addEventListener("click", handleDocumentClick);
      window.__favorites_click_bound__ = true;
    }

    // 提前创建 dialog，避免第一次打开有“抖动”
    ensureDialog();

    // 初始化收藏夹模式 UI（大星星 + banner）
    ensureFavoritesModeUI();
  }

  function open(projectId) {
    openSaveDialog(projectId);
  }

  window.Favorites = {
    init: init,
    open: open,
    openManager: openManager,
    enterFavoritesMode: enterFavoritesMode,
    exitFavoritesMode: exitFavoritesMode,
    ensureCollectionActive: ensureCollectionActive,
    getState: function () {
      return {
        isFavoritesMode: state.isFavoritesMode,
        activeCollectionId: state.activeCollectionId,
      };
    },
  };
})();
