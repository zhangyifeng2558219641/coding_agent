package com.example.mall.service;

import com.example.mall.entity.PointRecord;
import com.example.mall.entity.User;
import com.example.mall.repository.PointRecordRepository;
import com.example.mall.repository.UserRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 积分服务:我的积分流水、管理员调整积分(正/负,余额不可为负)
 */
@Service
public class PointService {

    private final PointRecordRepository pointRecordRepository;
    private final UserRepository userRepository;

    @Autowired
    public PointService(PointRecordRepository pointRecordRepository, UserRepository userRepository) {
        this.pointRecordRepository = pointRecordRepository;
        this.userRepository = userRepository;
    }

    public List<PointRecord> listMine(Long userId) {
        return pointRecordRepository.listByUser(userId);
    }

    /** 管理端:查看任意用户积分明细(校验用户存在) */
    public List<PointRecord> listByUser(Long userId) {
        if (userRepository.findById(userId) == null) {
            throw new IllegalArgumentException("用户不存在");
        }
        return pointRecordRepository.listByUser(userId);
    }

    @Transactional
    public User adminAdjust(Long targetUserId, int points, String remark) {
        User target = userRepository.findById(targetUserId);
        if (target == null) {
            throw new IllegalArgumentException("用户不存在");
        }
        int newBalance = target.getPoints() + points;
        if (newBalance < 0) {
            throw new IllegalArgumentException("调整后积分不能为负,当前余额 " + target.getPoints());
        }
        userRepository.updatePoints(targetUserId, newBalance);
        String finalRemark = (remark == null || remark.isBlank()) ? "管理员调整" : remark;
        pointRecordRepository.insert("ADMIN", points, newBalance, null, finalRemark, targetUserId);
        return userRepository.findById(targetUserId);
    }
}
