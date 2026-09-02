package com.example.mall.dto;

import jakarta.validation.constraints.NotNull;

/**
 * 管理员调整用户积分请求
 * points: 变动数量,正为增加、负为扣减
 */
public class AdjustPointsRequest {

    @NotNull(message = "积分变动数量不能为空")
    private Integer points;

    private String remark;

    public Integer getPoints() {
        return points;
    }

    public void setPoints(Integer points) {
        this.points = points;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }
}
