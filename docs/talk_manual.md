• 是的。核心应该替换 MemTalk_ShowMemorySentence，地址 0x0890F080，原名 sub_890F080。

  这是最终“记忆句子”真正拼出来并送进文本引擎的函数。你要做自然中文语序，应该在这里接管：

  void *MemTalk_ShowMemorySentence(
      ActionListContext *ctx,
      const ActionRecord *rec,
      const char *verbSjis
  );

  它现在做的是：

  简单句:
  $aは、昔の出来事を%s。

  详细句:
  $aは$bに、
  %sの出来事を%s。$n
  {place}{maskA}{が}{maskB}{expandedTemplate}を。

  中文化后不要再走这个日语骨架，而是在 sub_890F080 里改成：

  {speaker}{talkTargetPart}{verbPart}{timePart}{placePart}{eventClause}的事。

  也就是：

  碇真嗣回想起今早在 NERV 食堂向明日香搭话的事。
  碇真嗣向明日香回想起昨天在学校教室里绫波无视自己的事。

  不建议优先替换 MemTalk_ExpandActionTemplate / sub_890FA58。那个函数只知道 prefix/suffix/$a/$b，它太底层，不知
  道整句中文语序、时间、地点、说话对象，也不知道何时该省略主语。你如果只替换它，还是会被外层日语骨架卡住。

  完整 patch 面建议是：

  | 目的 | 替换函数 |
  |---|---|
  | 最终详细句/简单句/尾句 | MemTalk_ShowMemorySentence at 0x0890F080 |
  | 菜单列表里的短摘要 | MemTalk_FormatActionSummary25 at 0x0890F6B8，或更彻底替换 MemTalk_BuildMenuEntryList at
  0x0890F410 |
  | 候选记录筛选排序 | 不替换，保留 sub_890F2C4 |
  | 原始模板 prefix/suffix 展开 | 不作为主 patch 点，最多当参考 |

  如果你只关心点进记忆后的最终句子，替换 0x0890F080 就够了。

  如果你还想菜单列表也中文化，就要处理 0x0890F6B8。但注意：原始菜单摘要只有大约 0x19 字节限制，中文很容易爆。认
  真做的话，最好替换 MemTalk_BuildMenuEntryList，让它使用你自己的短摘要缓冲，而不是硬塞进原来的 25 字节。

  0x0890F080 的新逻辑大概应该是：

  CnMemTalk_ShowMemorySentence(ctx, rec, verb) {
      if (!(speaker == player || target == player))
          return;

      if (!rec || (rec->maskA & rec->maskB & 0xFFFFFF) != 0) {
          build_chinese_simple_sentence(...);
      } else {
          event = RenderChineseEvent(
              rec->templateId,
              rec->maskA,
              rec->maskB,
              ctx->speakerBit
          );

          time = RenderChineseTime(rec);
          place = RenderChinesePlace(rec, ctx->speakerBit);

          build_chinese_detail_sentence(
              speaker,
              targetBit,
              verb,
              time,
              place,
              event
          );
      }

      sub_882FD7C(0, ctx->speakerBit, ctx->targetBit, 0, buffer);

      if (ctx->speakerBit == 16 && ctx->targetBit != 0)
          show_chinese_tail_sentence(...);
  }

  关键是 RenderChineseEvent() 查你那张 templateId -> 中文模板 表，例如：

  2:  "向{B}搭话"
  4:  "无视{B}"
  7:  "冷淡地回应{B}"
  17: "因{B}的态度受打击"

  然后根据 maskA/maskB/styleBit 填 {A}、{B}、{A_ref}。

  所以一句话结论：

  最终句子替换 sub_890F080；菜单摘要另替换 sub_890F6B8 或 sub_890F410；不要动 sub_890F2C4，也不要把 sub_890FA58
  当主战场。