#include <stddef.h>

#include "hook_write.h"

static char *SentencePatch_Strcpy(char *dest, const char *src)
{
    char *ret = dest;
    while ((*dest++ = *src++) != '\0') {
    }
    return ret;
}

static void SentencePatch_WriteString(u32 game_base, u32 original_addr, const char *text)
{
    SentencePatch_Strcpy((char *)HookWrite_GameAddr(game_base, original_addr), text);
}

void SentencePatch_Install(u32 game_base)
{
    SentencePatch_WriteString(game_base, 0x089b4a94, "碇真嗣");
    SentencePatch_WriteString(game_base, 0x089b4aa4, "惣流・明日香・兰格雷");
    SentencePatch_WriteString(game_base, 0x089b4acc, "绫波丽");
    SentencePatch_WriteString(game_base, 0x089b4adc, "葛城美里");
    SentencePatch_WriteString(game_base, 0x089b4aec, "碇源堂");
    SentencePatch_WriteString(game_base, 0x089b4afc, "冬月耕造");
    SentencePatch_WriteString(game_base, 0x089b4b10, "赤木律子");
    SentencePatch_WriteString(game_base, 0x089b4b20, "伊吹摩耶");
    SentencePatch_WriteString(game_base, 0x089b4b30, "日向诚");
    SentencePatch_WriteString(game_base, 0x089b4b40, "青叶茂");
    SentencePatch_WriteString(game_base, 0x089b4b50, "加持良治");
    SentencePatch_WriteString(game_base, 0x089b4b64, "洞木光");
    SentencePatch_WriteString(game_base, 0x089b4b74, "铃原冬二");
    SentencePatch_WriteString(game_base, 0x089b4b84, "相田剑介");
    SentencePatch_WriteString(game_base, 0x089b4b98, "渚薰");
    SentencePatch_WriteString(game_base, 0x089b4ba8, "Pen Pen");
    SentencePatch_WriteString(game_base, 0x089b4bb8, "使徒、袭来");
    SentencePatch_WriteString(game_base, 0x089b4bc8, "但是、我爱这个世界");
    SentencePatch_WriteString(game_base, 0x089b4be8, "丽、心的彼方");
    SentencePatch_WriteString(game_base, 0x089b4c04, "亲吻脆弱的地方");
    SentencePatch_WriteString(game_base, 0x089b4c28, "女人的战斗");
    SentencePatch_WriteString(game_base, 0x089b4c38, "人类补完计划");
    SentencePatch_WriteString(game_base, 0x089b4c4c, "未完成的白日梦");
    SentencePatch_WriteString(game_base, 0x089b4c64, "女人如火");
    SentencePatch_WriteString(game_base, 0x089b4c70, "花样年华");
    SentencePatch_WriteString(game_base, 0x089b4c80, "暧昧的天空");
    SentencePatch_WriteString(game_base, 0x089b4c90, "Cobalt Sky");
    SentencePatch_WriteString(game_base, 0x089b4ca8, "VS．SEELE");
    SentencePatch_WriteString(game_base, 0x089b4cbc, "心中的一切");
    SentencePatch_WriteString(game_base, 0x089b4cd8, "从梦中醒来");
    SentencePatch_WriteString(game_base, 0x089b4cf0, "看见春天的人");
    SentencePatch_WriteString(game_base, 0x089b4d04, "折断的翅膀");
    SentencePatch_WriteString(game_base, 0x089b4d14, "人手难及");
    SentencePatch_WriteString(game_base, 0x089b4d3c, "「芝村」平衡");
    SentencePatch_WriteString(game_base, 0x089b4da0, "日目");
    SentencePatch_WriteString(game_base, 0x089b4da8, "结束");
    SentencePatch_WriteString(game_base, 0x089b4db0, "剧情通关文件");
    SentencePatch_WriteString(game_base, 0x089b4dd4, "开放剧情数");
    SentencePatch_WriteString(game_base, 0x089b4df0, "完成剧情数");
    SentencePatch_WriteString(game_base, 0x089b4d64, "零");
    SentencePatch_WriteString(game_base, 0x089b4d68, "一");
    SentencePatch_WriteString(game_base, 0x089b4d6c, "二");
    SentencePatch_WriteString(game_base, 0x089b4d70, "三");
    SentencePatch_WriteString(game_base, 0x089b4d74, "四");
    SentencePatch_WriteString(game_base, 0x089b4d78, "五");
    SentencePatch_WriteString(game_base, 0x089b4d7c, "六");
    SentencePatch_WriteString(game_base, 0x089b4d80, "七");
    SentencePatch_WriteString(game_base, 0x089b4d84, "八");
    SentencePatch_WriteString(game_base, 0x089b4d88, "九");
    SentencePatch_WriteString(game_base, 0x089b4d8c, "十");
    SentencePatch_WriteString(game_base, 0x089b4d90, "第");
    SentencePatch_WriteString(game_base, 0x089b4d94, "话");
    SentencePatch_WriteString(game_base, 0x089b4d98, "「");
    SentencePatch_WriteString(game_base, 0x089b4d9c, "」");
    SentencePatch_WriteString(game_base, 0x089b51c4, "AM");
    SentencePatch_WriteString(game_base, 0x089b51c8, "PM");
    SentencePatch_WriteString(game_base, 0x089b4e14, "加载完成。");
    SentencePatch_WriteString(game_base, 0x089b4e38, "保存完成。");
    SentencePatch_WriteString(game_base, 0x089b4e5c, "Memory Stick™空闲容量不足。\n\n");
    SentencePatch_WriteString(game_base, 0x089b4ea8, "本标题还需要\n");
    SentencePatch_WriteString(game_base, 0x089b4ecc, "游戏数据(");
    SentencePatch_WriteString(game_base, 0x089b4ee0, "KB)和\n");
    SentencePatch_WriteString(game_base, 0x089b4ee8, "剧情通关数据(");
    SentencePatch_WriteString(game_base, 0x089b4f08, "KB)的\n");
    SentencePatch_WriteString(game_base, 0x089b4f10, "空闲容量。\n\n");
    SentencePatch_WriteString(game_base, 0x089b4f3c, "是否删除其他游戏数据？");
    SentencePatch_WriteString(game_base, 0x089b4f74, "是否继续游戏？");
    SentencePatch_WriteString(game_base, 0x089b4f98, "是否中止保存？");
    SentencePatch_WriteString(game_base, 0x089b4fbc, "未找到Memory Stick™。\n\n");
    SentencePatch_WriteString(game_base, 0x089b4ff8, "本标题需要保存游戏数据(");
    SentencePatch_WriteString(game_base, 0x089b5024, "KB)的\n");
    SentencePatch_WriteString(game_base, 0x089b502c, "空闲容量。\n\n");
    SentencePatch_WriteString(game_base, 0x089b5070, "中止保存，继续游戏吗？");
    SentencePatch_WriteString(game_base, 0x089b50ac, "无法访问Memory Stick™。\n\n");
    SentencePatch_WriteString(game_base, 0x089b50f4, "无法保存到Memory Stick™。\n\n是否删除其他游戏数据后再次保存？");
    SentencePatch_WriteString(game_base, 0x089ea084, "新世纪福音战士２　被创造的世界");
    SentencePatch_WriteString(game_base, 0x089ea0c4, "空闲存档槽");
    SentencePatch_WriteString(game_base, 0x089ea0d8, "Memory Stick™尚未完成加载。\n\n是否停止加载，继续游戏？");
}
